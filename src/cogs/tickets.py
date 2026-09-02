import asyncio
import io
import re
import time

import discord
from discord import app_commands
from discord.ext import commands
import logging

from ..services import database as db
from ..services import modlog as modlog_service
from ..config import is_staff, STAFF_ROLE_NAMES
from ..services.permissions import permission_manager

logger = logging.getLogger("OmniBot.tickets")

TICKET_CATEGORY = "TICKETS"
MAX_OPEN_TICKETS = 1
REOPEN_COOLDOWN = 60

_reopen_cooldown = {}


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
        guild = interaction.guild
        user = interaction.user

        count = await db.get_open_ticket_count(user.id)
        if count >= MAX_OPEN_TICKETS:
            await interaction.response.send_message(
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
                await interaction.response.send_message(
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
        for role_name in STAFF_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
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
            await interaction.response.send_message(
                "❌ No tengo permisos para crear el canal del ticket.",
                ephemeral=True,
            )
            return

        ticket_id = await db.create_ticket(channel.id, user.id, self.subject.value)
        ticket = {"id": ticket_id, "subject": self.subject.value}

        desc = self.description.value.strip()
        intro = _ticket_embed(ticket, user)
        view = TicketButtons()
        await channel.send(user.mention, embed=intro, view=view)
        if desc:
            await channel.send(f"**📝 Descripción:**\n{desc}")

        logger.info(f"Ticket #{ticket_id} opened by {user} in #{channel.name}")
        await interaction.response.send_message(
            f"✅ Ticket creado: {channel.mention}",
            ephemeral=True,
        )


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎫 Abrir Ticket",
        style=discord.ButtonStyle.green,
        custom_id="ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        now = time.time()
        if now - _reopen_cooldown.get(user.id, 0) < REOPEN_COOLDOWN:
            await interaction.response.send_message(
                f"⏳ Esperá {REOPEN_COOLDOWN}s antes de abrir otro ticket.",
                ephemeral=True,
            )
            return

        count = await db.get_open_ticket_count(user.id)
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

    async def _get_ticket(self, channel_id: int) -> dict | None:
        ticket = await db.get_ticket_by_channel(channel_id)
        if not ticket:
            return None
        return ticket

    @discord.ui.button(
        label="🔒 Cerrar",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close",
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self._get_ticket(interaction.channel_id)
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
            view=ConfirmCloseView(ticket),
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

        ticket = await self._get_ticket(interaction.channel_id)
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
    def __init__(self, ticket: dict):
        super().__init__(timeout=60)
        self.ticket = ticket
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
        if self._done:
            return
        self._done = True
        ticket = self.ticket
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not channel:
            await interaction.edit_original_response(content="El canal ya no existe.")
            return

        transcript = await build_transcript(channel)
        await db.close_ticket(ticket["id"])
        _reopen_cooldown[ticket["user_id"]] = time.time()

        log_channel = await modlog_service.get_or_create_modlogs(interaction.guild)
        if log_channel:
            creator = interaction.guild.get_member(ticket["user_id"]) or await safe_fetch_user(
                interaction.client, ticket["user_id"]
            )
            embed = discord.Embed(
                title="🎫 Ticket cerrado",
                description=(
                    f"**Asunto:** {ticket['subject']}\n"
                    f"**Creador:** {creator.mention if creator else ticket['user_id']}\n"
                    f"**Cerrado por:** {interaction.user.mention}\n"
                    f"**ID:** #{ticket['id']}"
                ),
                color=0xED4245,
                timestamp=discord.utils.utcnow(),
            )
            try:
                await log_channel.send(
                    embed=embed,
                    file=discord.File(
                        io.BytesIO(transcript.encode("utf-8")),
                        filename=f"ticket-{ticket['id']}.txt",
                    ),
                )
            except discord.Forbidden:
                logger.warning("No permissions to post transcript in #mod-logs")

        try:
            await channel.send(
                "🔒 Ticket cerrado. El canal se eliminará en 5 segundos.",
                delete_after=5,
            )
        except discord.HTTPException:
            pass

        async def _delete_later():
            await asyncio.sleep(5)
            try:
                await channel.delete(reason=f"Ticket #{ticket['id']} closed by {interaction.user}")
            except discord.NotFound:
                logger.info(f"Ticket #{ticket['id']} channel already deleted")
            except discord.HTTPException as e:
                logger.error(f"Error deleting ticket channel: {e}")

        asyncio.create_task(_delete_later())

        logger.info(f"Ticket #{ticket['id']} closed by {interaction.user}")

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
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


async def build_transcript(channel: discord.TextChannel, limit: int = 300) -> str:
    lines = [f"Transcript del canal #{channel.name}", "=" * 40, ""]
    async for msg in channel.history(limit=limit, oldest_first=True):
        if msg.author.bot and msg.embeds:
            lines.append(f"[{msg.created_at:%d/%m/%Y %H:%M}] BOT: (embed)")
            continue
        content = (msg.content or "").replace("\n", " ")
        content = content[:1500] if len(content) > 1500 else content
        if content:
            lines.append(f"[{msg.created_at:%d/%m/%Y %H:%M}] {msg.author}: {content}")
    return "\n".join(lines)


class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
