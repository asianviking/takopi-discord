"""Slash command and message handlers for Discord."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .client import DiscordBotClient
    from .mapping import CategoryChannelMapper
    from .state import DiscordStateStore


def register_slash_commands(
    bot: DiscordBotClient,
    *,
    state_store: DiscordStateStore,
    mapper: CategoryChannelMapper,
    get_running_task: callable,
    cancel_task: callable,
) -> None:
    """Register slash commands with the bot."""
    tree = bot.tree

    @tree.command(name="status", description="Show current channel context and status")
    async def status_command(interaction: discord.Interaction) -> None:
        """Show current channel context and running tasks."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id
        guild_id = interaction.guild.id

        # Get context from state or infer from channel
        context = await state_store.get_context(guild_id, channel_id)
        if context is None:
            mapping = mapper.get_channel_mapping(guild_id, channel_id)
            if mapping is not None:
                context = mapper.get_context_from_mapping(mapping)

        if context is None:
            await interaction.response.send_message(
                "No context configured for this channel.\n"
                "Use `/bind <project>` to set up this channel.",
                ephemeral=True,
            )
            return

        # Check for running task
        running = get_running_task(channel_id)
        status_line = "idle"
        if running is not None:
            status_line = f"running (message #{running})"

        message = (
            f"**Channel Status**\n"
            f"- Project: `{context.project}`\n"
            f"- Branch: `{context.branch}`\n"
            f"- Status: {status_line}"
        )
        await interaction.response.send_message(message, ephemeral=True)

    @tree.command(name="bind", description="Bind this channel to a project")
    @app_commands.describe(
        project="The project name to bind to this channel",
        branch="Optional branch override (defaults to channel name)",
    )
    async def bind_command(
        interaction: discord.Interaction,
        project: str,
        branch: str | None = None,
    ) -> None:
        """Bind a channel to a project."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id
        guild_id = interaction.guild.id

        # Get branch from channel name if not provided
        if branch is None:
            mapping = mapper.get_channel_mapping(guild_id, channel_id)
            branch = mapping.branch if mapping is not None else "main"

        from .types import DiscordChannelContext

        context = DiscordChannelContext(project=project, branch=branch)
        await state_store.set_context(guild_id, channel_id, context)

        await interaction.response.send_message(
            f"Bound channel to project `{project}` branch `{branch}`.",
            ephemeral=True,
        )

    @tree.command(name="unbind", description="Remove project binding from this channel")
    async def unbind_command(interaction: discord.Interaction) -> None:
        """Unbind a channel from its project."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id
        guild_id = interaction.guild.id

        await state_store.clear_channel(guild_id, channel_id)
        await interaction.response.send_message(
            "Channel binding removed.", ephemeral=True
        )

    @tree.command(name="cancel", description="Cancel the currently running task")
    async def cancel_command(interaction: discord.Interaction) -> None:
        """Cancel a running task."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id

        running = get_running_task(channel_id)
        if running is None:
            await interaction.response.send_message(
                "No task is currently running in this channel.", ephemeral=True
            )
            return

        await cancel_task(channel_id)
        await interaction.response.send_message(
            "Cancellation requested.", ephemeral=True
        )


def is_bot_mentioned(message: discord.Message, bot_user: discord.User | None) -> bool:
    """Check if the bot is mentioned in the message."""
    if bot_user is None:
        return False
    return bot_user in message.mentions


def should_process_message(
    message: discord.Message,
    bot_user: discord.User | None,
    *,
    require_mention: bool = False,
) -> bool:
    """Determine if a message should be processed by the bot.

    Args:
        message: The Discord message
        bot_user: The bot's user object
        require_mention: If True, only process messages that mention the bot
    """
    # Ignore bot messages
    if message.author.bot:
        return False

    # Ignore empty messages
    if not message.content.strip():
        return False

    # In threads, always process
    if isinstance(message.channel, discord.Thread):
        return True

    # In channels, check if mention is required
    if require_mention:
        return is_bot_mentioned(message, bot_user)

    return True


def extract_prompt_from_message(
    message: discord.Message,
    bot_user: discord.User | None,
) -> str:
    """Extract the prompt text from a message, removing bot mentions."""
    content = message.content

    # Remove bot mention if present
    if bot_user is not None:
        content = content.replace(f"<@{bot_user.id}>", "").strip()
        content = content.replace(f"<@!{bot_user.id}>", "").strip()

    return content
