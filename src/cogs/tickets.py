import asyncio
import hashlib
import json
import os
import tempfile
import zipfile
import re
import time

import discord
from discord import app_commands
from discord.ext import commands
import logging

from ..services import database as db
from ..services import modlog as modlog_service
from ..config import is_staff
from ..services.permissions import permission_manager

logger = logging.getLogger("OmniBot.tickets")

TICKET_CATEGORY = "TICKETS"


async def data_available(interaction):
    check = getattr(interaction.client, "check_data_ready", None)
    return await check(interaction) if check else True

MAX_OPEN_TICKETS = 1
REOPEN_COOLDOWN = 60

_reopen_cooldown = {}
_ticket_locks = {}


def _sanitize_channel_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\-]", "", name.lower())
    return (cleaned or "usuario")[:25]


def _ticket_embed(ticket: dict, member: discord.Member | discord.User) -> discord.Embed:
    embed = discord.Embed(
        title="🎫 Ticket abierto",
        description=(
            f"**Asunto:** {ticket['subject']}\n"
            f"**Creado por:** {member.mention}\n"
            f"**ID:** #{ticket['id']}\n\n"
            "Un miembro del staff te atenderá en breve.\n"
            "Describe tu problema con el mayor detalle posible."
        ),
        color=0x5865F2,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Usa 🔒 Cerrar cuando esté resuelto · 🙋 Reclamar es solo para staff")
    return embed


class TicketModal(discord.ui.Modal, title="Nuevo Ticket"):
    subject = discord.ui.TextInput(
        label="Asunto",
        placeholder="Resumen breve del problema (ej: No puedo entrar al server)",
        max_length=100,
        required=True,
    )
    description = discord.ui.TextInput(
        label="Descripción",
        style=discord.TextStyle.paragraph,
        placeholder="Detalles: qué pasó, cuándo, capturas si tenés...",
        max_length=1000,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not await data_available(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        key = (interaction.guild.id, interaction.user.id)
        lock = _ticket_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._submit(interaction)

    async def _submit(self, interaction):
        guild = interaction.guild
        user = interaction.user

        count = await db.get_open_ticket_count(user.id, guild_id=guild.id)
        if count >= MAX_OPEN_TICKETS:
            await interaction.followup.send(
                f"❌ Ya tenés un ticket abierto (máximo {MAX_OPEN_TICKETS}). "
                "Cerralo antes de abrir otro.",
                ephemeral=True,
            )
            return

        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
        if category is None:
            try:
                category = await guild.create_category(TICKET_CATEGORY)
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ No tengo permisos para crear la categoría de tickets.",
                    ephemeral=True,
                )
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_channels=True,
                manage_messages=True, read_message_history=True,
            ),
            user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True,
            ),
        }
        for role in permission_manager.staff_roles(guild):
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True,
                )

        channel_name = f"ticket-{_sanitize_channel_name(user.name)}"
        try:
            channel = await guild.create_text_channel(
                channel_name, category=category, overwrites=overwrites
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ No tengo permisos para crear el canal del ticket.",
                ephemeral=True,
            )
            return

        ticket_id = await db.create_ticket(channel.id, user.id, self.subject.value, guild_id=guild.id)
        ticket = {"id": ticket_id, "subject": self.subject.value}

        desc = self.description.value.strip()
        intro = _ticket_embed(ticket, user)
        view = TicketButtons()
        await channel.send(user.mention, embed=intro, view=view)
        if desc:
            await channel.send(f"**📝 Descripción:**\n{desc}")

        logger.info(f"Ticket #{ticket_id} opened by {user} in #{channel.name}")
        await interaction.followup.send(
            f"✅ Ticket creado: {channel.mention}",
            ephemeral=True,
        )


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        return await data_available(interaction)

    @discord.ui.button(
        label="🎫 Abrir Ticket",
        style=discord.ButtonStyle.green,
        custom_id="ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        now = time.time()
        if now - _reopen_cooldown.get((interaction.guild.id, user.id), 0) < REOPEN_COOLDOWN:
            await interaction.response.send_message(
                f"⏳ Esperá {REOPEN_COOLDOWN}s antes de abrir otro ticket.",
                ephemeral=True,
            )
            return

        count = await db.get_open_ticket_count(user.id, guild_id=interaction.guild.id)
        if count >= MAX_OPEN_TICKETS:
            await interaction.response.send_message(
                f"❌ Ya tenés un ticket abierto (máximo {MAX_OPEN_TICKETS}).",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TicketModal())


class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_ticket(self, channel_id: int, guild_id: int) -> dict | None:
        ticket = await db.get_ticket_by_channel(channel_id, guild_id=guild_id)
        if not ticket:
            return None
        return ticket

    async def interaction_check(self, interaction):
        return await data_available(interaction)

    @discord.ui.button(
        label="🔒 Cerrar",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close",
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self._get_ticket(interaction.channel_id, interaction.guild.id)
        if not ticket:
            await interaction.response.send_message(
                "Este ticket ya está cerrado o no existe.", ephemeral=True
            )
            return

        is_owner = interaction.user.id == ticket["user_id"]
        if not is_owner and not is_staff(interaction.user):
            await interaction.response.send_message(
                "Solo el dueño del ticket o el staff puede cerrarlo.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "¿Seguro que querés cerrar este ticket? El canal se eliminará y se guardará un registro.",
            ephemeral=True,
            view=ConfirmCloseView(ticket, interaction.user.id),
        )

    @discord.ui.button(
        label="🙋 Reclamar",
        style=discord.ButtonStyle.blurple,
        custom_id="ticket_claim",
    )
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "Solo el staff puede reclamar tickets.", ephemeral=True
            )
            return

        ticket = await self._get_ticket(interaction.channel_id, interaction.guild.id)
        if not ticket:
            await interaction.response.send_message(
                "Este ticket ya está cerrado o no existe.", ephemeral=True
            )
            return

        await db.claim_ticket(ticket["id"], interaction.user.id)
        await interaction.response.send_message(
            f"🙋 Ticket reclamado por {interaction.user.mention}",
        )


class ConfirmCloseView(discord.ui.View):
    def __init__(self, ticket: dict, requester_id: int):
        super().__init__(timeout=60)
        self.ticket = ticket
        self.requester_id = requester_id
        self._done = False

    async def _disable_buttons(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="✅ Confirmar cierre", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Solo quien pidió el cierre puede confirmarlo.", ephemeral=True)
            return
        if self._done:
            await interaction.response.send_message("Cierre ya procesado.", ephemeral=True)
            return
        self._done = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = _ticket_locks.setdefault((interaction.guild.id, self.ticket["channel_id"]), asyncio.Lock())
        async with lock:
            try:
                ticket = await db.get_ticket_by_channel(self.ticket["channel_id"], guild_id=interaction.guild.id)
                if not ticket:
                    await interaction.edit_original_response(content="El ticket ya está cerrado.")
                    return
                actor = await interaction.guild.fetch_member(interaction.user.id)
                if actor.id != ticket["user_id"] and not is_staff(actor):
                    await interaction.edit_original_response(content="Ya no tienes permisos para cerrar este ticket.")
                    return
                channel = interaction.guild.get_channel(ticket["channel_id"])
                if channel is None:
                    await interaction.edit_original_response(content="El canal no existe; el registro se conserva.")
                    return
                archive_path, digest = await archive_ticket(channel, ticket["id"])
                log_channel = await modlog_service.get_or_create_modlogs(interaction.guild)
                if log_channel is None:
                    raise RuntimeError("No hay canal privado de registros disponible")
                embed = discord.Embed(
                    title="🎫 Ticket archivado",
                    description=f"Ticket #{ticket['id']} · creador <@{ticket['user_id']}> · cerrado por {actor.mention}\nSHA-256: `{digest}`",
                    color=0xED4245,
                )
                kwargs = {"embed": embed, "allowed_mentions": discord.AllowedMentions.none()}
                if os.path.getsize(archive_path) <= interaction.guild.filesize_limit:
                    kwargs["file"] = discord.File(archive_path, filename=f"ticket-{ticket['id']}.zip")
                else:
                    embed.add_field(name="Archivo completo", value="Guardado en el volumen persistente de transcripts; excede el límite de adjuntos de Discord.")
                try:
                    receipt = await log_channel.send(**kwargs)
                finally:
                    if "file" in kwargs:
                        kwargs["file"].close()
                await db.set_setting(f"ticket_archive_{ticket['id']}", json.dumps({
                    "path": archive_path, "sha256": digest, "log_message_id": receipt.id,
                }))
                await channel.delete(reason=f"Ticket #{ticket['id']} archivado por {actor}")
                await db.close_ticket(ticket["id"])
                _reopen_cooldown[(interaction.guild.id, ticket["user_id"])] = time.time()
                await interaction.edit_original_response(content="Ticket archivado y cerrado.", view=None)
                self.stop()
            except Exception:
                self._done = False
                logger.exception("Cierre de ticket fallido; no se elimina sin archivo y registro confirmados")
                await interaction.edit_original_response(content="No pude completar el cierre. El archivo o canal se conserva; puedes volver a intentarlo.")

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Solo quien pidió el cierre puede cancelarlo.", ephemeral=True)
            return
        await interaction.response.defer()
        if self._done:
            return
        self._done = True
        await self._disable_buttons(interaction)
        await interaction.edit_original_response(content="Cierre cancelado.")


async def safe_fetch_user(bot, user_id: int) -> discord.User | None:
    try:
        return await bot.fetch_user(user_id)
    except discord.NotFound:
        return None


def transcript_message(msg):
    lines = [f"[{msg.created_at.isoformat()}] {msg.author} (ID {msg.author.id}) · mensaje {msg.id}", msg.content or ""]
    for attachment in msg.attachments:
        lines.append(f"Adjunto: {attachment.filename} · {attachment.url}")
    for embed in msg.embeds:
        lines.append("Embed: " + json.dumps(embed.to_dict(), ensure_ascii=False))
    return "\n".join(lines)


async def build_transcript(channel: discord.TextChannel, limit: int | None = None) -> str:
    lines = [f"Transcript del canal #{channel.name} (ID {channel.id})", "=" * 40, ""]
    async for msg in channel.history(limit=limit, oldest_first=True):
        lines.append(transcript_message(msg))
    return "\n".join(lines)


async def archive_ticket(channel, ticket_id):
    directory = os.path.join(db.DB_DIR, "transcripts", str(channel.guild.id))
    os.makedirs(directory, exist_ok=True)
    final_path = os.path.join(directory, f"ticket-{ticket_id}-{time.time_ns()}.zip")
    with tempfile.TemporaryDirectory(dir=directory) as temp_dir:
        transcript_path = os.path.join(temp_dir, "transcript.txt")
        attachment_paths = []
        with open(transcript_path, "w", encoding="utf-8") as transcript:
            transcript.write(f"Ticket #{ticket_id} · canal {channel.id}\n")
            async for msg in channel.history(limit=None, oldest_first=True):
                transcript.write(transcript_message(msg) + "\n\n")
                for attachment in msg.attachments:
                    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", attachment.filename)[:100]
                    filename = f"{attachment.id}-{safe_name}"
                    local = os.path.join(temp_dir, filename)
                    await attachment.save(local)
                    attachment_paths.append((local, "attachments/" + filename))
        def pack():
            partial = os.path.join(temp_dir, "archive.zip")
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(transcript_path, "transcript.txt")
                for local, name in attachment_paths:
                    archive.write(local, name)
            digest = hashlib.sha256()
            with open(partial, "rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(chunk)
                os.fsync(file.fileno())
            os.replace(partial, final_path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return digest.hexdigest()
        digest = await asyncio.to_thread(pack)
    return final_path, digest


class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name="ticketpanel", description="Publicar el panel de tickets (ADMIN)")
    async def ticketpanel_cmd(self, interaction: discord.Interaction):
        if not permission_manager.has_permission(interaction.user, "ticket_panel"):
            await interaction.response.send_message("Necesitas permisos de **ADMINISTRADOR** para usar este comando.")
            return

        embed = discord.Embed(
            title="🎫 SOPORTE / TICKETS",
            description=(
                "¿Tenés un problema o una consulta para el staff?\n"
                "Click el botón para abrir un ticket privado.\n\n"
                "• Un miembro del staff te atenderá\n"
                "• Podés cerrarlo cuando esté resuelto\n"
                "• Máximo 1 ticket abierto por usuario"
            ),
            color=0x5865F2,
        )
        await interaction.response.send_message(embed=embed, view=TicketView())
        logger.info(f"Ticket panel posted by {interaction.user}")


async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
