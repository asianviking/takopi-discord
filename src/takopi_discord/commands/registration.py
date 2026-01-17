"""Dynamic slash command registration for plugin commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from takopi.commands import get_command, list_command_ids
from takopi.logging import get_logger
from takopi.model import EngineId
from takopi.runner_bridge import RunningTasks
from takopi.runners.run_options import EngineRunOptions

from .dispatch import dispatch_command

if TYPE_CHECKING:
    from ..bridge import DiscordBridgeConfig
    from ..client import DiscordBotClient
    from ..state import DiscordStateStore

logger = get_logger(__name__)


def discover_command_ids(allowlist: set[str] | None) -> set[str]:
    """Discover available command plugin IDs."""
    return {cmd_id.lower() for cmd_id in list_command_ids(allowlist=allowlist)}


def register_plugin_commands(
    bot: DiscordBotClient,
    cfg: DiscordBridgeConfig,
    *,
    command_ids: set[str],
    running_tasks: RunningTasks,
    state_store: DiscordStateStore,
    default_engine_override: EngineId | None,
) -> None:
    """Register slash commands for discovered plugins.

    Args:
        bot: The Discord bot client
        cfg: Bridge configuration
        command_ids: Set of plugin command IDs to register
        running_tasks: Running tasks dictionary for cancellation
        state_store: State store for resolving overrides
        default_engine_override: Default engine override
    """
    pycord_bot = bot.bot

    for command_id in sorted(command_ids):
        backend = get_command(
            command_id, allowlist=cfg.runtime.allowlist, required=False
        )
        if backend is None:
            logger.warning("plugin.not_found", command_id=command_id)
            continue

        # Truncate description to Discord's 100 char limit
        description = backend.description
        if len(description) > 100:
            description = description[:97] + "..."

        # Create a factory function to capture command_id in closure
        def make_command(cmd_id: str, desc: str):
            @pycord_bot.slash_command(name=cmd_id, description=desc)
            async def plugin_command(
                ctx: discord.ApplicationContext,
                args: str = discord.Option(default="", description="Command arguments"),
            ) -> None:
                await _handle_plugin_command(
                    ctx,
                    command_id=cmd_id,
                    args_text=args,
                    cfg=cfg,
                    running_tasks=running_tasks,
                    state_store=state_store,
                    default_engine_override=default_engine_override,
                )

            return plugin_command

        make_command(command_id, description)
        logger.info("plugin.registered", command_id=command_id, description=description)


async def _handle_plugin_command(
    ctx: discord.ApplicationContext,
    *,
    command_id: str,
    args_text: str,
    cfg: DiscordBridgeConfig,
    running_tasks: RunningTasks,
    state_store: DiscordStateStore,
    default_engine_override: EngineId | None,
) -> None:
    """Handle a plugin slash command invocation."""
    from ..overrides import resolve_overrides

    if ctx.guild is None:
        await ctx.respond("This command can only be used in a server.", ephemeral=True)
        return

    # Defer to give us time to process
    await ctx.defer()

    guild_id = ctx.guild.id
    channel_id = ctx.channel_id
    thread_id = None

    if isinstance(ctx.channel, discord.Thread):
        thread_id = ctx.channel_id
        if ctx.channel.parent_id:
            channel_id = ctx.channel.parent_id

    # Create engine overrides resolver
    async def engine_overrides_resolver(
        engine_id: EngineId,
    ) -> EngineRunOptions | None:
        overrides = await resolve_overrides(
            state_store, guild_id, channel_id, thread_id, engine_id
        )
        if overrides.model or overrides.reasoning:
            return EngineRunOptions(
                model=overrides.model,
                reasoning=overrides.reasoning,
            )
        return None

    # Build full text as it would appear in a message
    full_text = f"/{command_id} {args_text}".strip()

    # For slash commands, we don't have a real message ID yet
    # Use 0 as a placeholder - the executor will handle this
    message_id = 0

    # Dispatch to the plugin
    handled = await dispatch_command(
        cfg,
        command_id=command_id,
        args_text=args_text,
        full_text=full_text,
        channel_id=thread_id or channel_id,  # Send to thread if in one
        message_id=message_id,
        guild_id=guild_id,
        thread_id=thread_id,
        reply_ref=None,  # Slash commands don't have a message to reply to
        reply_text=None,
        running_tasks=running_tasks,
        on_thread_known=None,  # We don't track sessions for plugin commands
        default_engine_override=default_engine_override,
        engine_overrides_resolver=engine_overrides_resolver,
    )

    # If dispatch didn't send anything, acknowledge completion
    if not handled:
        await ctx.followup.send(f"Command `/{command_id}` not found.", ephemeral=True)
    elif not ctx.response.is_done():
        # If the plugin didn't send a response, send a minimal acknowledgment
        await ctx.followup.send("Done.", ephemeral=True)
