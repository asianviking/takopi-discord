"""Slash command and message handlers for Discord."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from .client import DiscordBotClient
    from .state import DiscordStateStore
    from .voice import VoiceManager


def register_slash_commands(
    bot: DiscordBotClient,
    *,
    state_store: DiscordStateStore,
    get_running_task: callable,
    cancel_task: callable,
    voice_manager: VoiceManager | None = None,
) -> None:
    """Register slash commands with the bot."""
    tree = bot.tree

    @tree.command(name="status", description="Show current channel context and status")
    async def status_command(interaction: discord.Interaction) -> None:
        """Show current channel context and running tasks."""
        from .types import DiscordThreadContext

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id
        guild_id = interaction.guild.id

        # Get context from state
        context = await state_store.get_context(guild_id, channel_id)

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

        # Format message based on context type
        if isinstance(context, DiscordThreadContext):
            # Thread context (has specific branch)
            message = (
                f"**Thread Status**\n"
                f"- Project: `{context.project}`\n"
                f"- Branch: `{context.branch}`\n"
                f"- Worktrees dir: `{context.worktrees_dir}`\n"
                f"- Engine: `{context.default_engine}`\n"
                f"- Status: {status_line}"
            )
        else:
            # Channel context (no specific branch, uses worktree_base as default)
            message = (
                f"**Channel Status**\n"
                f"- Project: `{context.project}`\n"
                f"- Default branch: `{context.worktree_base}`\n"
                f"- Worktrees dir: `{context.worktrees_dir}`\n"
                f"- Engine: `{context.default_engine}`\n"
                f"- Status: {status_line}\n\n"
                f"_Use `@branch-name` to create a thread for a specific branch._"
            )
        await interaction.response.send_message(message, ephemeral=True)

    @tree.command(name="bind", description="Bind this channel to a project")
    @app_commands.describe(
        project="The project path (e.g., ~/dev/myproject)",
        worktrees_dir="Directory for git worktrees (default: .worktrees)",
        default_engine="Default engine to use (default: claude)",
        worktree_base="Base branch for worktrees and default working branch (default: master)",
    )
    async def bind_command(
        interaction: discord.Interaction,
        project: str,
        worktrees_dir: str = ".worktrees",
        default_engine: str = "claude",
        worktree_base: str = "master",
    ) -> None:
        """Bind a channel to a project."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        channel_id = interaction.channel_id
        guild_id = interaction.guild.id

        from .types import DiscordChannelContext

        context = DiscordChannelContext(
            project=project,
            worktrees_dir=worktrees_dir,
            default_engine=default_engine,
            worktree_base=worktree_base,
        )
        await state_store.set_context(guild_id, channel_id, context)

        await interaction.response.send_message(
            f"Bound channel to project `{project}`\n"
            f"- Default branch: `{worktree_base}`\n"
            f"- Worktrees dir: `{worktrees_dir}`\n"
            f"- Engine: `{default_engine}`\n\n"
            f"_Use `@branch-name` to create threads for specific branches._",
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

    # Voice commands (only register if voice_manager is provided)
    if voice_manager is not None:
        _register_voice_commands(
            bot, state_store=state_store, voice_manager=voice_manager
        )


def _register_voice_commands(
    bot: DiscordBotClient,
    *,
    state_store: DiscordStateStore,
    voice_manager: VoiceManager,
) -> None:
    """Register voice-related slash commands."""
    tree = bot.tree

    @tree.command(
        name="voice",
        description="Create a voice channel for this thread/channel and join it",
    )
    async def voice_command(interaction: discord.Interaction) -> None:
        """Create a voice channel bound to the current thread/channel's project context.

        If run in a thread, inherits the thread's project and branch.
        If run in a channel, inherits the channel's project and base branch.
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        guild_id = interaction.guild.id
        channel = interaction.channel

        # Determine the text channel ID and get context
        text_channel_id = interaction.channel_id
        if text_channel_id is None:
            await interaction.response.send_message(
                "Could not determine the channel.", ephemeral=True
            )
            return

        # Get context - check thread first, then parent channel
        context = None

        if isinstance(channel, discord.Thread):
            # Try thread-specific context first
            context = await state_store.get_context(guild_id, channel.id)
            if context is None and channel.parent_id:
                # Fall back to parent channel context
                context = await state_store.get_context(guild_id, channel.parent_id)
        else:
            context = await state_store.get_context(guild_id, text_channel_id)

        if context is None:
            await interaction.response.send_message(
                "This channel/thread is not bound to a project.\n"
                "Use `/bind <project>` first, then `/voice`.",
                ephemeral=True,
            )
            return

        # Defer since creating channel and joining might take a moment
        await interaction.response.defer(ephemeral=True)

        # Determine the branch name for the voice channel
        from .types import DiscordThreadContext

        if isinstance(context, DiscordThreadContext):
            branch = context.branch
        else:
            branch = context.worktree_base

        try:
            # Create a temporary voice channel
            # Name it after the thread/branch
            if isinstance(channel, discord.Thread):
                voice_name = f"Voice: {channel.name[:90]}"
            else:
                voice_name = f"Voice: {branch}"

            # Get the category of the current channel (if any) to create voice channel in same category
            category = None
            if isinstance(channel, discord.Thread) and channel.parent:
                category = channel.parent.category
            elif isinstance(channel, discord.TextChannel):
                category = channel.category

            voice_channel = await interaction.guild.create_voice_channel(
                name=voice_name,
                category=category,
                reason=f"Voice session for {context.project}:{branch}",
            )

            # Join the voice channel
            await voice_manager.join_channel(
                voice_channel,
                text_channel_id,  # Link back to the original text channel/thread
                context.project,
                branch,
            )

            await interaction.followup.send(
                f"Created voice channel **{voice_channel.name}**.\n"
                f"Project: `{context.project}` Branch: `{branch}`\n"
                f"Join to start talking. The channel will be deleted when everyone leaves.",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to create voice channels.",
                ephemeral=True,
            )
        except discord.ClientException as e:
            await interaction.followup.send(
                f"Failed to create/join voice channel: {e}",
                ephemeral=True,
            )

    # Register /vc as an alias for /voice
    @tree.command(
        name="vc",
        description="Create a voice channel for this thread/channel (alias for /voice)",
    )
    async def vc_command(interaction: discord.Interaction) -> None:
        """Alias for /voice command."""
        await voice_command.callback(interaction)


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


def parse_branch_prefix(content: str) -> tuple[str | None, str]:
    """Parse @branch prefix from message content.

    Returns (branch, remaining_prompt).

    Examples:
        "@chore/hello fix the bug" -> ("chore/hello", "fix the bug")
        "@feat-login" -> ("feat-login", "")
        "hello world" -> (None, "hello world")
    """
    content = content.strip()
    if not content.startswith("@"):
        return None, content

    # Find the end of the branch token (first whitespace or end of string)
    parts = content[1:].split(None, 1)  # Split on whitespace, max 2 parts
    if not parts:
        return None, content

    branch = parts[0]
    if not branch:
        return None, content

    remaining = parts[1] if len(parts) > 1 else ""
    return branch, remaining.strip()
