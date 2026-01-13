"""Main event loop for Discord transport."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

import anyio
import discord

from takopi.logging import get_logger
from takopi.markdown import MarkdownParts
from takopi.model import ResumeToken
from takopi.runner_bridge import RunningTasks
from takopi.transport import MessageRef, RenderedMessage, SendOptions

from .bridge import CANCEL_BUTTON_ID, DiscordBridgeConfig, DiscordTransport
from .handlers import (
    extract_prompt_from_message,
    register_slash_commands,
    should_process_message,
)
from .mapping import CategoryChannelMapper
from .render import prepare_discord
from .state import DiscordStateStore
from .types import DiscordChannelContext

if TYPE_CHECKING:
    from takopi.context import RunContext

logger = get_logger(__name__)

__all__ = ["run_main_loop"]


async def _send_startup(cfg: DiscordBridgeConfig, channel_id: int) -> None:
    """Send startup message to the specified channel."""
    logger.debug("startup.message", text=cfg.startup_msg)
    parts = MarkdownParts(header=cfg.startup_msg)
    text = prepare_discord(parts)
    message = RenderedMessage(text=text, extra={})
    sent = await cfg.exec_cfg.transport.send(
        channel_id=channel_id,
        message=message,
    )
    if sent is not None:
        logger.info("startup.sent", channel_id=channel_id)


async def run_main_loop(
    cfg: DiscordBridgeConfig,
    *,
    default_engine_override: str | None = None,
) -> None:
    """Run the main Discord event loop."""
    running_tasks: RunningTasks = {}
    config_path = cfg.runtime.config_path
    state_store = DiscordStateStore(config_path) if config_path else None
    mapper = CategoryChannelMapper(cfg.bot)
    transport = cast(DiscordTransport, cfg.exec_cfg.transport)

    def get_running_task(channel_id: int) -> int | None:
        """Get the message ID of a running task in a channel."""
        for key, task in running_tasks.items():
            if key[0] == channel_id:
                return key[1]
        return None

    async def cancel_task(channel_id: int) -> None:
        """Cancel a running task in a channel."""
        for key, task in list(running_tasks.items()):
            if key[0] == channel_id:
                task.cancel_scope.cancel()
                break

    # Register slash commands
    register_slash_commands(
        cfg.bot,
        state_store=state_store,
        mapper=mapper,
        get_running_task=get_running_task,
        cancel_task=cancel_task,
    )

    async def run_job(
        channel_id: int,
        user_msg_id: int,
        text: str,
        resume_token: ResumeToken | None,
        context: RunContext | None,
        thread_id: int | None = None,
        reply_ref: MessageRef | None = None,
    ) -> None:
        """Run an engine job."""
        from takopi.runner_bridge import run_engine

        await run_engine(
            exec_cfg=cfg.exec_cfg,
            runtime=cfg.runtime,
            running_tasks=running_tasks,
            chat_id=channel_id,
            user_msg_id=user_msg_id,
            text=text,
            resume_token=resume_token,
            context=context,
            reply_ref=reply_ref,
            thread_id=thread_id,
            show_resume_line=cfg.show_resume_line,
        )

    async def handle_message(message: discord.Message) -> None:
        """Handle an incoming Discord message."""
        if not should_process_message(message, cfg.bot.user, require_mention=False):
            return

        channel_id = message.channel.id
        guild_id = message.guild.id if message.guild else None
        thread_id = None

        # Check if this is a thread
        if isinstance(message.channel, discord.Thread):
            thread_id = message.channel.id
            parent = message.channel.parent
            if parent:
                channel_id = parent.id

        # Get context from state or infer from channel
        context_data: DiscordChannelContext | None = None
        if state_store and guild_id:
            context_data = await state_store.get_context(guild_id, channel_id)

        if context_data is None and guild_id:
            mapping = mapper.get_channel_mapping(guild_id, channel_id)
            if mapping:
                context_data = mapper.get_context_from_mapping(mapping)

        # Build run context if we have channel context
        run_context: RunContext | None = None
        if context_data:
            from takopi.context import RunContext

            run_context = RunContext(
                project=context_data.project,
                branch=context_data.branch,
            )

        # Extract prompt
        prompt = extract_prompt_from_message(message, cfg.bot.user)
        if not prompt.strip():
            return

        # Get resume token if in stateful mode
        resume_token: ResumeToken | None = None
        if state_store and guild_id and cfg.session_mode == "chat":
            engine_id = cfg.runtime.default_engine or "claude"
            token_str = await state_store.get_session(guild_id, channel_id, engine_id)
            if token_str:
                resume_token = ResumeToken(token_str)

        # Create thread for the response if not already in a thread
        if thread_id is None and isinstance(message.channel, discord.TextChannel):
            # Send initial reply then create thread from it
            pass  # For now, just reply in channel

        reply_ref = MessageRef(
            channel_id=channel_id,
            message_id=message.id,
            thread_id=thread_id,
        )

        logger.info(
            "message.received",
            channel_id=channel_id,
            message_id=message.id,
            author=message.author.name,
            prompt_length=len(prompt),
        )

        await run_job(
            channel_id=thread_id or channel_id,
            user_msg_id=message.id,
            text=prompt,
            resume_token=resume_token,
            context=run_context,
            thread_id=thread_id,
            reply_ref=reply_ref,
        )

    # Set up message handler
    cfg.bot.set_message_handler(handle_message)

    # Handle cancel button interactions
    @cfg.bot.client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        if not interaction.data:
            return
        custom_id = interaction.data.get("custom_id")
        if custom_id == CANCEL_BUTTON_ID:
            await transport.handle_cancel_interaction(interaction)

    # Start the bot
    await cfg.bot.start()

    # Send startup message to first available text channel
    if cfg.guild_id:
        guild = cfg.bot.get_guild(cfg.guild_id)
        if guild:
            for channel in guild.text_channels:
                await _send_startup(cfg, channel.id)
                break

    logger.info("bot.ready", user=cfg.bot.user.name if cfg.bot.user else "unknown")

    # Keep running until cancelled
    try:
        await anyio.sleep_forever()
    finally:
        await cfg.bot.close()
