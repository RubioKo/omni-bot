import asyncio
import json
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.cogs.assistant import AssistantCog, MultiConfirmView, build_confirmation_text
from src.cogs.community import CommunityCog
from src.cogs.setup import SetupCog
from src.cogs.tickets import ConfirmCloseView, TicketButtons, archive_ticket, build_transcript
from src.services.authorization import authorize_action
from src.services.permissions import PermissionManager, PermissionLevel, permission_manager
from src.utils.members import resolve_member


def interaction(guild, user):
    return SimpleNamespace(
        guild=guild, user=user, client=SimpleNamespace(), channel_id=10,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
        followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock(),
    )


def moderation_context():
    guild = SimpleNamespace(id=1, owner_id=99, roles=[], text_channels=[])
    actor = SimpleNamespace(id=2, mention="<@2>", guild=guild, roles=[], top_role=20, guild_permissions=discord.Permissions.all())
    target = SimpleNamespace(id=3, guild=guild, roles=[], top_role=10, bot=False, guild_permissions=discord.Permissions.none())
    guild.me = SimpleNamespace(id=4, top_role=30, guild_permissions=discord.Permissions.all())
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.guild, channel.mention = 10, guild, '<#10>'
    channel.permissions_for.return_value = discord.Permissions.all()
    guild.get_member = lambda uid: target if uid == target.id else actor
    guild.get_channel = lambda cid: channel if cid == channel.id else None
    guild.fetch_member = AsyncMock(side_effect=lambda uid: target if uid == target.id else actor)
    return guild, actor, target, channel


@pytest.mark.asyncio
async def test_repostroles_denies_non_owner_before_channel_operations():
    guild = SimpleNamespace(owner_id=99)
    i = interaction(guild, SimpleNamespace(id=2))
    await SetupCog(None).repostroles.callback(SetupCog(None), i)
    i.response.send_message.assert_awaited_once()
    i.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_preserves_existing_channels_and_history(db, monkeypatch):
    from src.cogs import setup
    role_names = ['Miembro', 'DJ', '🔫 Valorant Player', '🏗️ Fortnite Player', '⚔️ LoL Player',
                  '🎯 Arena Breakout Player', '🌸 Genshin Player', '⚔️ HotS Player', '🏆 Competitive',
                  '😎 Casual', '🎬 Creador', '👥 LFG', '🛡️ Staff Helper', '🏆 VIP']
    roles = [MagicMock(spec=discord.Role, name=n) for n in role_names]
    for idx, (role, name) in enumerate(zip(roles, role_names), 1):
        role.name, role.id = name, idx
    layout = {
        'INFORMACION': ['reglas', 'roles', 'anuncios'],
        'COMUNIDAD': ['general', 'off-topic', 'memes', 'clips-y-logros', 'presentaciones'],
        'JUEGOS': ['valorant', 'fortnite', 'lol', 'abi', 'genshin', 'hots', 'lfg'],
        'EVENTOS': ['game-nights', 'coach-corner', 'sugerencias'],
        'VOZ': ['🔊 General', '🔊 Gaming', '🔊 Music', '🔊 AFK'],
        'STAFF': ['staff-chat', 'mod-logs', '🔊 Staff Only'],
    }
    categories = []
    channels = []
    for name, names in layout.items():
        children = [SimpleNamespace(name=n, id=len(channels) + j + 1, delete=AsyncMock(), set_permissions=AsyncMock(), send=AsyncMock()) for j, n in enumerate(names)]
        channels.extend(children)
        categories.append(SimpleNamespace(name=name, channels=children, set_permissions=AsyncMock()))
    guild = SimpleNamespace(id=101, owner_id=99, roles=roles, categories=categories, channels=channels,
                            default_role=MagicMock(spec=discord.Role), create_category=AsyncMock(),
                            create_text_channel=AsyncMock(), create_voice_channel=AsyncMock(), create_forum_channel=AsyncMock())
    monkeypatch.setattr(setup, 'ConfirmView', lambda uid: SimpleNamespace(confirmed=True, wait=AsyncMock()))
    monkeypatch.setattr(permission_manager, 'role_bindings', {})
    i = interaction(guild, SimpleNamespace(id=99))
    cog = SetupCog(None)
    await cog.deploy.callback(cog, i)
    for channel in channels:
        channel.delete.assert_not_awaited()
        channel.set_permissions.assert_not_awaited()
        channel.send.assert_not_awaited()
    assert not permission_manager.role_bindings
    guild.create_category.assert_not_awaited()
    guild.create_text_channel.assert_not_awaited()
    guild.create_voice_channel.assert_not_awaited()
    guild.create_forum_channel.assert_not_awaited()


@pytest.mark.parametrize('action', ['warn_user', 'mute_user', 'unmute_user', 'kick_user', 'ban_user'])
def test_all_moderation_actions_enforce_actor_hierarchy(action):
    guild, actor, target, channel = moderation_context()
    target.top_role = 25
    assert 'superior al tuyo' in authorize_action(actor, guild, action, target=target, channel=channel)


def test_moderation_enforces_bot_permissions_and_channel_access():
    guild, actor, target, channel = moderation_context()
    perms = discord.Permissions.all()
    perms.view_channel = False
    channel.permissions_for.return_value = perms
    assert 'acceso' in authorize_action(actor, guild, 'mute_user', target=target, channel=channel)
    perms.view_channel = True
    perms.moderate_members = False
    assert 'Discord' in authorize_action(actor, guild, 'mute_user', target=target, channel=channel)


@pytest.mark.asyncio
async def test_confirmation_rechecks_current_permissions_before_any_action(monkeypatch):
    from src.cogs import assistant
    guild, actor, _, channel = moderation_context()
    original = SimpleNamespace(guild=guild, author=actor, channel=channel)
    view = MultiConfirmView([{'tool': 'mute_user', 'params': {'user': '<@3>', 'channel': '<#10>', 'duration': '60s'}}], actor, 'mute', 'ADMIN', original)
    actor.guild_permissions = discord.Permissions.none()
    monkeypatch.setattr(permission_manager, 'role_bindings', {guild.id: {}})
    tool = AsyncMock()
    monkeypatch.setitem(assistant.TOOL_MAP, 'mute_user', tool)
    i = interaction(guild, actor)
    await view.confirm.callback(i)
    tool.assert_not_awaited()
    assert 'cancelada' in i.edit_original_response.call_args.kwargs['content']


def test_confirmation_contains_all_effects():
    text = build_confirmation_text([{'tool': 'clear_messages', 'params': {'count': 42, 'channel': '<#10>'}},
                                    {'tool': 'set_slowmode', 'params': {'seconds': 60, 'channel': '<#11>'}}])
    assert '42 mensajes' in text and '60 segundos' in text and '<#10>' in text and '<#11>' in text


@pytest.mark.asyncio
async def test_server_data_isolation(db):
    await db.add_xp(1, 401, guild_id=10)
    await db.add_xp(1, 25, guild_id=20)
    assert (await db.get_level(1, guild_id=10))['level'] == 2
    assert (await db.get_level(1, guild_id=20))['xp'] == 25
    await db.add_warning(1, 2, 'private', guild_id=10)
    assert not await db.get_active_warnings(1, guild_id=20)
    assert await db.clear_warnings(1, guild_id=20) == 0
    await db.log_mod_action(1, 'WARN', 2, 'private', guild_id=10)
    assert not await db.get_modlog(guild_id=20)
    await db.create_ticket(10, 1, 'private', guild_id=10)
    assert await db.get_open_ticket_count(1, guild_id=20) == 0
    assert await db.get_ticket_by_channel(10, guild_id=20) is None
    await db.add_meme_history('url', 'private', guild_id=10)
    assert not await db.is_meme_seen('url', guild_id=20)
    await db.record_meme_feedback('url', 'source', 3, guild_id=10)
    assert await db.get_weekly_winner(guild_id=20) is None


def test_conversation_isolated_by_guild_and_channel():
    cog = AssistantCog(None)
    cog._remember((1, 10, 3), 'user', 'private')
    assert cog._get_history((2, 10, 3)) == []
    assert cog._get_history((1, 20, 3)) == []


@pytest.mark.asyncio
async def test_migrate_old_database_backs_up_and_preserves_rows(db):
    await db.close_db()
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute('DROP TABLE levels')
    conn.execute('CREATE TABLE levels (user_id INTEGER PRIMARY KEY, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1, last_xp_time REAL DEFAULT 0, last_voice_time REAL DEFAULT 0)')
    conn.execute('INSERT INTO levels VALUES (7, 12, 4, 0, 0)')
    conn.commit()
    conn.close()
    await db.init_db()
    assert (await db.get_level(7))['level'] == 4
    from pathlib import Path
    assert list(Path(db.DB_DIR, 'backups').glob('pre-guild-migration-*.db'))
    guilds = [SimpleNamespace(id=10, channels=[]), SimpleNamespace(id=20, channels=[])]
    await db.assign_legacy_data(guilds)
    assert (await db.get_level(7, guild_id=10))['level'] == 1
    await db.assign_legacy_data(guilds, 20)
    assert (await db.get_level(7, guild_id=20))['level'] == 4
    await db.init_db()
    assert (await db.get_level(7, guild_id=20))['level'] == 4


@pytest.mark.asyncio
async def test_rank_matches_leaderboard_across_levels_and_ties(db):
    for uid, amount in [(2, 401), (1, 401), (3, 399)]:
        await db.add_xp(uid, amount, guild_id=10)
    top = await db.get_leaderboard(guild_id=10)
    assert [r['user_id'] for r in top] == [1, 2, 3]
    assert [await db.get_user_rank_position(r['user_id'], guild_id=10) for r in top] == [1, 2, 3]


@pytest.mark.asyncio
async def test_spam_window_does_not_accumulate_slow_messages(db, monkeypatch):
    counts = []
    for now in [100, 109, 118, 127, 136]:
        monkeypatch.setattr(time, 'time', lambda: now)
        counts.append(await db.track_spam(1, 2, 10, guild_id=10))
    assert counts == [1, 2, 2, 2, 2]
    assert await db.track_spam(1, 2, 10, guild_id=20) == 1


@pytest.mark.asyncio
async def test_permission_role_ids_survive_renames_and_reject_same_name(db):
    manager = PermissionManager()
    role = SimpleNamespace(id=55, name='MODERADOR')
    guild = SimpleNamespace(id=1, owner_id=99, roles=[role])
    await manager.load_guild(guild)
    member = SimpleNamespace(id=2, roles=[role], guild=guild, guild_permissions=discord.Permissions.none())
    role.name = 'Renamed'
    assert manager.get_permission_level(member) == PermissionLevel.MODERATOR
    member.roles = [SimpleNamespace(id=66, name='MODERADOR')]
    assert manager.get_permission_level(member) == PermissionLevel.MEMBER
    member.id = 99
    assert manager.get_permission_level(member) == PermissionLevel.OWNER
    member.id = 2
    member.guild_permissions.administrator = True
    assert manager.get_permission_level(member) == PermissionLevel.ADMIN
    await manager.bind_role(guild.id, 66, PermissionLevel.MODERATOR)
    loaded = PermissionManager()
    await loaded.load_guild(guild)
    member.guild_permissions.administrator = False
    assert loaded.get_permission_level(member) == PermissionLevel.MODERATOR


def test_ambiguous_member_resolution_fails_closed():
    members = [SimpleNamespace(id=i, name=name, nick=None) for i, name in [(1, 'Carlos A'), (2, 'Carlos B')]]
    guild = SimpleNamespace(members=members, get_member=lambda uid: next((m for m in members if m.id == uid), None))
    assert resolve_member(guild, 'Carlos') is None
    assert resolve_member(guild, 'arlos') is None
    assert resolve_member(guild, '<@2>').id == 2
    assert resolve_member(guild, '1').id == 1
    assert resolve_member(guild, '<@999>') is None


async def messages(items):
    for item in items:
        yield item


def transcript_items(count=301):
    return [SimpleNamespace(id=i, created_at=datetime.now(timezone.utc), author=SimpleNamespace(id=1, bot=False),
                            content='x' * 1600, attachments=[], embeds=[]) for i in range(count)]


@pytest.mark.asyncio
async def test_transcript_contains_all_messages_embeds_and_attachments(db):
    items = transcript_items()
    attachment = SimpleNamespace(id=1, filename='proof.txt', url='https://example.com/proof')
    async def save(path):
        with open(path, 'wb') as file:
            file.write(b'proof')
    attachment.save = save
    items[-1].attachments = [attachment]
    items[-1].embeds = [discord.Embed(description='evidence')]
    channel = SimpleNamespace(id=10, name='ticket', guild=SimpleNamespace(id=20), history=MagicMock(side_effect=lambda **kw: messages(items)))
    text = await build_transcript(channel)
    assert 'mensaje 300' in text and 'evidence' in text and 'proof.txt' in text
    assert 'x' * 1600 in text
    path, digest = await archive_ticket(channel, 1)
    assert len(digest) == 64
    with zipfile.ZipFile(path) as archive:
        assert 'mensaje 300' in archive.read('transcript.txt').decode()
        assert any(archive.read(n) == b'proof' for n in archive.namelist() if n.startswith('attachments/'))


@pytest.mark.asyncio
async def test_failed_transcript_log_never_deletes_ticket(db, monkeypatch):
    from src.cogs import tickets
    guild, actor, _, channel = moderation_context()
    guild.filesize_limit = 100000
    channel.delete = AsyncMock()
    tid = await db.create_ticket(channel.id, actor.id, 'test', guild_id=guild.id)
    ticket = await db.get_ticket_by_channel(channel.id, guild_id=guild.id)
    path = str(__import__('pathlib').Path(db.DB_DIR, 'test.zip'))
    __import__('pathlib').Path(path).write_bytes(b'archive')
    monkeypatch.setattr(tickets, 'archive_ticket', AsyncMock(return_value=(path, 'digest')))
    monkeypatch.setattr(tickets.modlog_service, 'get_or_create_modlogs', AsyncMock(return_value=SimpleNamespace(send=AsyncMock(side_effect=RuntimeError('offline')))))
    view = ConfirmCloseView(ticket, actor.id)
    i = interaction(guild, actor)
    await view.confirm.callback(i)
    channel.delete.assert_not_awaited()
    assert (await db.get_ticket_by_channel(channel.id, guild_id=guild.id))['id'] == tid
    assert not view._done
    tickets.modlog_service.get_or_create_modlogs.return_value.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_ticket_close_archives_before_delete(db, monkeypatch):
    from src.cogs import tickets
    guild, actor, _, channel = moderation_context()
    guild.filesize_limit = 100000
    events = []
    async def delete(**kwargs):
        events.append('delete')
        assert await db.get_setting('ticket_archive_1')
    async def send(**kwargs):
        events.append('log')
        return SimpleNamespace(id=42)
    channel.delete = AsyncMock(side_effect=delete)
    await db.create_ticket(channel.id, actor.id, 'test', guild_id=guild.id)
    ticket = await db.get_ticket_by_channel(channel.id, guild_id=guild.id)
    from pathlib import Path
    path = Path(db.DB_DIR, 'test.zip')
    path.write_bytes(b'archive')
    monkeypatch.setattr(tickets, 'archive_ticket', AsyncMock(return_value=(str(path), 'digest')))
    monkeypatch.setattr(tickets.modlog_service, 'get_or_create_modlogs', AsyncMock(return_value=SimpleNamespace(send=send)))
    view = ConfirmCloseView(ticket, actor.id)
    await view.confirm.callback(interaction(guild, actor))
    assert events == ['log', 'delete']
    assert await db.get_ticket_by_channel(channel.id, guild_id=guild.id) is None


@pytest.mark.asyncio
async def test_persistent_ticket_buttons_registered_and_error_handler_connected(monkeypatch):
    from src.bot import OmniBot
    from src.services import database
    import wavelink
    import uvicorn
    bot = OmniBot()
    monkeypatch.setattr(database, 'init_db', AsyncMock())
    monkeypatch.setattr(bot, 'load_extension', AsyncMock())
    monkeypatch.setattr(wavelink.Node, '__init__', lambda self, **kw: None)
    monkeypatch.setattr(wavelink.Pool, 'connect', AsyncMock())
    monkeypatch.setattr(bot.tree, 'sync', AsyncMock(return_value=[]))
    monkeypatch.setattr(bot.daily_meme, 'start', MagicMock())
    monkeypatch.setattr(bot.db_backup, 'start', MagicMock())
    monkeypatch.setattr(uvicorn.Server, 'serve', AsyncMock())
    try:
        await bot.setup_hook()
        assert any(isinstance(v, TicketButtons) for v in bot.persistent_views)
        assert bot.tree.on_error == bot.on_app_command_error
    finally:
        await bot.close()


@pytest.mark.parametrize('responded', [True, False])
@pytest.mark.asyncio
async def test_error_handler_handles_both_interaction_states(responded):
    from src.bot import OmniBot
    bot = OmniBot()
    i = interaction(None, None)
    i.command = SimpleNamespace(qualified_name='test')
    i.response.is_done = lambda: responded
    await bot.on_app_command_error(i, discord.app_commands.CheckFailure('denied'))
    (i.followup.send if responded else i.response.send_message).assert_awaited_once()
    await bot.close()


@pytest.mark.asyncio
async def test_giveaway_retry_keeps_winners_and_finishes_only_after_delivery(db):
    channel = SimpleNamespace(fetch_message=AsyncMock(), history=MagicMock(side_effect=lambda **kw: messages([])), send=AsyncMock(side_effect=RuntimeError('offline')))
    guild = SimpleNamespace(id=1, get_channel=lambda cid: channel)
    bot = SimpleNamespace(user=SimpleNamespace(id=99), get_guild=lambda gid: guild, report_task_error=AsyncMock())
    cog = CommunityCog(bot)
    gid = await db.create_giveaway(1, 10, 'prize', 1, time.time() - 10, 2)
    await db.save_giveaway_result(gid, [7])
    await cog._check_giveaways()
    row = await db.get_giveaway(gid)
    assert row['active'] == 1 and json.loads(row['result']) == [7] and row['attempts'] == 1
    conn = await db._get_db()
    await conn.execute('UPDATE giveaways SET next_attempt=0')
    await conn.commit()
    channel.send.side_effect = None
    await cog._check_giveaways()
    assert (await db.get_giveaway(gid))['active'] == 0
    assert '<@7>' in channel.send.call_args.kwargs['embed'].description
    channel.fetch_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_failure_is_retained_and_existing_receipt_prevents_duplicate(db):
    guild = SimpleNamespace(id=1)
    channel = SimpleNamespace(guild=guild, history=MagicMock(side_effect=lambda **kw: messages([])), send=AsyncMock(side_effect=RuntimeError('offline')))
    bot = SimpleNamespace(user=SimpleNamespace(id=99), get_channel=lambda cid: channel, report_task_error=AsyncMock())
    cog = CommunityCog(bot)
    rid = await db.create_reminder(7, 10, 'test', time.time()-10, guild_id=1)
    await cog._check_reminders()
    conn = await db._get_db()
    rows = await conn.execute_fetchall('SELECT * FROM reminders')
    assert len(rows) == 1 and rows[0]['attempts'] == 1
    marker = f'omnibot:reminder:1:{rid}'
    embed = discord.Embed().set_footer(text=marker)
    delivered = SimpleNamespace(author=bot.user, embeds=[embed])
    channel.history.side_effect = lambda **kw: messages([delivered])
    channel.send.reset_mock()
    await conn.execute('UPDATE reminders SET next_attempt=0')
    await conn.commit()
    await cog._check_reminders()
    channel.send.assert_not_awaited()
    assert not await conn.execute_fetchall('SELECT * FROM reminders')


@pytest.mark.asyncio
async def test_lockdown_restores_explicit_and_inherited_permissions_after_restart(db, monkeypatch):
    from src.services.lockdown import set_lockdown, FIELDS
    everyone = MagicMock(spec=discord.Role)
    everyone.id, everyone.permissions = 1, discord.Permissions.none()
    member_role = MagicMock(spec=discord.Role)
    member_role.id, member_role.permissions = 2, discord.Permissions.none()
    staff = MagicMock(spec=discord.Role)
    staff.id, staff.permissions = 3, discord.Permissions.none()
    originals = {everyone: discord.PermissionOverwrite(send_messages=None, embed_links=True),
                 member_role: discord.PermissionOverwrite(send_messages=True, send_messages_in_threads=True),
                 staff: discord.PermissionOverwrite(send_messages=True)}
    current = {role: discord.PermissionOverwrite.from_pair(*ow.pair()) for role, ow in originals.items()}
    channel = SimpleNamespace(id=10, name='general', category=None, overwrites=current)
    channel.overwrites_for = lambda role: discord.PermissionOverwrite.from_pair(*current.get(role, discord.PermissionOverwrite()).pair())
    async def set_permissions(target, overwrite, **kwargs):
        current[target] = overwrite or discord.PermissionOverwrite()
    channel.set_permissions = AsyncMock(side_effect=set_permissions)
    guild = SimpleNamespace(id=99, default_role=everyone, text_channels=[channel], forums=[], me=SimpleNamespace(id=4),
                            get_channel=lambda cid: channel, get_role=lambda rid: next((r for r in originals if r.id == rid), None))
    monkeypatch.setattr(permission_manager, 'staff_roles', lambda g: [staff])
    await set_lockdown(guild, True)
    assert current[everyone].send_messages is False
    assert current[member_role].send_messages_in_threads is False
    assert current[staff].send_messages is True
    assert current[everyone].embed_links is True
    snapshot = await db.get_setting('lockdown_99')
    await set_lockdown(guild, True)
    assert await db.get_setting('lockdown_99') == snapshot
    await db.close_db()
    await db.init_db()
    await set_lockdown(guild, False)
    for role in (everyone, member_role):
        for field in FIELDS:
            assert getattr(current[role], field) == getattr(originals[role], field)
    assert current[everyone].embed_links is True
    assert not await db.get_setting('lockdown_99')


@pytest.mark.asyncio
async def test_concurrent_confirmation_executes_at_most_once(monkeypatch):
    from src.cogs import assistant
    guild, actor, _, channel = moderation_context()
    message = SimpleNamespace(guild=guild, author=actor, channel=channel)
    view = MultiConfirmView([{'tool': 'mute_user', 'params': {'user': '<@3>', 'channel': '<#10>'}}], actor, 'mute', 'ADMIN', message)
    tool = AsyncMock(return_value='done')
    monkeypatch.setitem(assistant.TOOL_MAP, 'mute_user', tool)
    monkeypatch.setattr(assistant, 'prepare_action', AsyncMock(return_value=(actor, None, channel, '')))
    monkeypatch.setattr(assistant.brain, 'compose_response', AsyncMock(return_value='done'))
    await asyncio.gather(view.confirm.callback(interaction(guild, actor)), view.confirm.callback(interaction(guild, actor)))
    tool.assert_awaited_once()


@pytest.mark.parametrize('duration', ['-1h', '1h basura', '1hour', '1.5h', '10', ''])
def test_duration_rejects_partial_or_negative_inputs(duration):
    from src.utils.helpers import parse_duration
    assert parse_duration(duration) == 0


@pytest.mark.parametrize('seconds', [True, 1.5, -1, 21601])
def test_slowmode_validation_rejects_invalid_values(seconds):
    from src.cogs.assistant import validate_tool_params
    assert not validate_tool_params('set_slowmode', {'seconds': seconds})[0]


@pytest.mark.asyncio
async def test_moderation_tool_never_mutates_unauthorized_target(db):
    from src.tools.moderation import mute_user
    guild, actor, target, channel = moderation_context()
    target.top_role = actor.top_role
    target.timeout = AsyncMock()
    message = SimpleNamespace(guild=guild, author=actor, channel=channel)
    result = await mute_user(None, message, {'user': '<@3>', 'duration': '60s'})
    assert 'superior al tuyo' in result
    target.timeout.assert_not_awaited()
    assert not await db.get_modlog(guild_id=guild.id)


@pytest.mark.asyncio
async def test_legacy_assignment_rolls_back_inferred_channels_on_invalid_destination(db):
    await db.create_ticket(10, 1, 'legacy')
    guild = SimpleNamespace(id=1, channels=[SimpleNamespace(id=10)])
    with pytest.raises(ValueError):
        await db.assign_legacy_data([guild], 2)
    assert await db.get_ticket_by_channel(10, guild_id=0)
    assert not await db.get_ticket_by_channel(10, guild_id=1)
