"""Main event loop for Discord transport."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

import anyio
import discord

from takopi.logging import get_logger
from takopi.markdown import MarkdownParts
from takopi.model import ResumeToken
from takopi.runner_bridge import RunningTasks
from takopi.transport import MessageRef, RenderedMessage

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
    state_store = DiscordStateStore(cfg.runtime.config_path)
    mapper = CategoryChannelMapper(cfg.bot)
    transport = cast(DiscordTransport, cfg.exec_cfg.transport)

    logger.info(
        "loop.config",
        session_mode=cfg.session_mode,
        has_state_store=state_store is not None,
        guild_id=cfg.guild_id,
    )

    def get_running_task(channel_id: int) -> int | None:
        """Get the message ID of a running task in a channel."""
        for ref in running_tasks:
            # ref is a MessageRef; check both channel_id and thread_id
            if ref.channel_id == channel_id or ref.thread_id == channel_id:
                return ref.message_id
        return None

    async def cancel_task(channel_id: int) -> None:
        """Cancel a running task in a channel."""
        for ref, task in list(running_tasks.items()):
            # ref is a MessageRef; check both channel_id and thread_id
            if ref.channel_id == channel_id or ref.thread_id == channel_id:
                task.cancel_requested.set()
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
        guild_id: int | None = None,
    ) -> None:
        """Run an engine job."""
        from takopi.config import ConfigError
        from takopi.logging import bind_run_context, clear_context
        from takopi.runner_bridge import IncomingMessage
        from takopi.runner_bridge import handle_message as takopi_handle_message
        from takopi.utils.paths import reset_run_base_dir, set_run_base_dir

        logger.info(
            "run_job.start",
            channel_id=channel_id,
            user_msg_id=user_msg_id,
            text_length=len(text),
            has_context=context is not None,
            project=context.project if context else None,
            branch=context.branch if context else None,
        )

        try:
            # Resolve the runner
            resolved = cfg.runtime.resolve_runner(
                resume_token=resume_token,
                engine_override=default_engine_override,
            )
            if not resolved.available:
                logger.error(
                    "run_job.runner_unavailable",
                    engine=resolved.engine,
                    issue=resolved.issue,
                )
                return

            # Resolve working directory
            try:
                cwd = cfg.runtime.resolve_run_cwd(context)
            except ConfigError as exc:
                logger.error("run_job.cwd_error", error=str(exc))
                return

            run_base_token = set_run_base_dir(cwd)
            try:
                # Bind logging context
                run_fields = {
                    "chat_id": channel_id,
                    "user_msg_id": user_msg_id,
                    "engine": resolved.runner.engine,
                    "resume": resume_token.value if resume_token else None,
                }
                if context is not None:
                    run_fields["project"] = context.project
                    run_fields["branch"] = context.branch
                if cwd is not None:
                    run_fields["cwd"] = str(cwd)
                bind_run_context(**run_fields)

                # Build incoming message
                incoming = IncomingMessage(
                    channel_id=channel_id,
                    message_id=user_msg_id,
                    text=text,
                    reply_to=reply_ref,
                    thread_id=thread_id,
                )

                # Build context line if we have context
                context_line = cfg.runtime.format_context_line(context)

                # Callback to save the resume token when it becomes known
                async def on_thread_known(
                    new_token: ResumeToken, _event: anyio.Event
                ) -> None:
                    logger.debug(
                        "on_thread_known.called",
                        guild_id=guild_id,
                        channel_id=channel_id,
                        thread_id=thread_id,
                        session_mode=cfg.session_mode,
                        token_preview=new_token.value[:20] + "..." if len(new_token.value) > 20 else new_token.value,
                    )
                    if state_store and guild_id and cfg.session_mode == "chat":
                        engine_id = cfg.runtime.default_engine or "claude"
                        # Save to thread_id if present, otherwise channel_id
                        # This matches the retrieval logic in handle_message
                        save_key = thread_id if thread_id else channel_id
                        await state_store.set_session(
                            guild_id, save_key, engine_id, new_token.value
                        )
                        logger.info(
                            "session.saved",
                            guild_id=guild_id,
                            session_key=save_key,
                            engine_id=engine_id,
                        )
                    else:
                        logger.debug(
                            "on_thread_known.not_saving",
                            has_state_store=state_store is not None,
                            guild_id=guild_id,
                            session_mode=cfg.session_mode,
                        )

                await takopi_handle_message(
                    cfg.exec_cfg,
                    runner=resolved.runner,
                    incoming=incoming,
                    resume_token=resume_token,
                    context=context,
                    context_line=context_line,
                    strip_resume_line=cfg.runtime.is_resume_line,
                    running_tasks=running_tasks,
                    on_thread_known=on_thread_known,
                )
                logger.info("run_job.complete", channel_id=channel_id)
            finally:
                reset_run_base_dir(run_base_token)
        except Exception:
            logger.exception("run_job.error", channel_id=channel_id)
        finally:
            clear_context()

    async def handle_message(message: discord.Message) -> None:
        """Handle an incoming Discord message."""
        print(f"[DEBUG handle_message] ENTERED - channel={message.channel.id} author={message.author.name}", flush=True)
        logger.debug(
            "message.raw",
            channel_type=type(message.channel).__name__,
            channel_id=message.channel.id,
            author=message.author.name,
            content_preview=message.content[:50] if message.content else "",
        )
        if not should_process_message(message, cfg.bot.user, require_mention=False):
            logger.debug("message.skipped", reason="should_process_message returned False")
            print(f"[DEBUG handle_message] should_process_message returned False, returning", flush=True)
            return

        print(f"[DEBUG handle_message] passed should_process_message", flush=True)
        channel_id = message.channel.id
        guild_id = message.guild.id if message.guild else None
        thread_id = None
        is_new_thread = False

        # Check if this is a thread
        if isinstance(message.channel, discord.Thread):
            thread_id = message.channel.id
            parent = message.channel.parent
            if parent:
                channel_id = parent.id
            print(f"[DEBUG handle_message] in thread: thread_id={thread_id} parent_channel_id={channel_id}", flush=True)
            logger.debug(
                "message.in_thread",
                thread_id=thread_id,
                parent_channel_id=channel_id,
            )
            # Ensure we're a member of the thread so we receive future messages
            with contextlib.suppress(discord.HTTPException):
                await message.channel.join()

        print(f"[DEBUG handle_message] about to get context from state_store", flush=True)
        # Get context from state or infer from channel
        context_data: DiscordChannelContext | None = None
        if state_store and guild_id:
            print(f"[DEBUG handle_message] calling state_store.get_context(guild_id={guild_id}, channel_id={channel_id})", flush=True)
            context_data = await state_store.get_context(guild_id, channel_id)

        print(f"[DEBUG handle_message] got context_data from state_store: {context_data}", flush=True)
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
        print(f"[DEBUG handle_message] extracted prompt: '{prompt[:50] if prompt else ''}'", flush=True)
        if not prompt.strip():
            print(f"[DEBUG handle_message] empty prompt, returning", flush=True)
            return

        # Create thread for the response if not already in a thread
        if thread_id is None and isinstance(message.channel, discord.TextChannel):
            # Create a thread from the user's message
            thread_name = prompt[:100] if len(prompt) <= 100 else prompt[:97] + "..."
            created_thread_id = await cfg.bot.create_thread(
                channel_id=channel_id,
                message_id=message.id,
                name=thread_name,
            )
            if created_thread_id is not None:
                thread_id = created_thread_id
                is_new_thread = True
                logger.info(
                    "thread.created",
                    channel_id=channel_id,
                    thread_id=thread_id,
                    name=thread_name,
                )

        # Get resume token if in stateful mode
        # For threads, use thread_id as the session key to maintain conversation continuity
        # within the thread (regardless of which specific message is being replied to)
        resume_token: ResumeToken | None = None
        session_key = thread_id if thread_id else channel_id
        print(f"[DEBUG handle_message] session_mode={cfg.session_mode} session_key={session_key}", flush=True)
        logger.debug(
            "session.lookup",
            guild_id=guild_id,
            session_key=session_key,
            session_mode=cfg.session_mode,
            has_state_store=state_store is not None,
        )
        if state_store and guild_id and cfg.session_mode == "chat":
            engine_id = cfg.runtime.default_engine or "claude"
            print(f"[DEBUG handle_message] about to call state_store.get_session(guild_id={guild_id}, session_key={session_key}, engine_id={engine_id})", flush=True)
            try:
                token_str = await state_store.get_session(guild_id, session_key, engine_id)
                print(f"[DEBUG handle_message] got token_str: {token_str[:20] if token_str else None}...", flush=True)
            except Exception as e:
                print(f"[DEBUG handle_message] EXCEPTION in get_session: {e}", flush=True)
                import traceback
                traceback.print_exc()
                raise
            if token_str:
                try:
                    resume_token = ResumeToken(engine=engine_id, value=token_str)
                    print(f"[DEBUG handle_message] created resume_token from token_str", flush=True)
                except Exception as e:
                    print(f"[DEBUG handle_message] EXCEPTION creating ResumeToken: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    raise
                logger.info(
                    "session.restored",
                    guild_id=guild_id,
                    session_key=session_key,
                    engine_id=engine_id,
                    token_preview=token_str[:20] + "..." if len(token_str) > 20 else token_str,
                )
            else:
                logger.debug(
                    "session.not_found",
                    guild_id=guild_id,
                    session_key=session_key,
                    engine_id=engine_id,
                )

        print(f"[DEBUG handle_message] building reply_ref, is_new_thread={is_new_thread}", flush=True)
        # For new threads, don't set reply_ref since the original message is in the parent channel
        # and runner_bridge creates its own user_ref that would be incorrect for cross-channel replies
        reply_ref: MessageRef | None = None
        if not is_new_thread:
            reply_ref = MessageRef(
                channel_id=channel_id,
                message_id=message.id,
                thread_id=thread_id,
            )

        print(f"[DEBUG handle_message] about to call run_job with resume_token={resume_token is not None}", flush=True)
        logger.info(
            "message.received",
            channel_id=channel_id,
            thread_id=thread_id,
            session_key=session_key,
            message_id=message.id,
            author=message.author.name,
            prompt_length=len(prompt),
            has_context=run_context is not None,
            is_new_thread=is_new_thread,
            has_resume_token=resume_token is not None,
        )

        # For new threads, use thread_id as channel_id since that's where we're sending
        # For existing threads/channels, thread_id already specifies where to send
        job_channel_id = thread_id if thread_id else channel_id

        try:
            print(f"[DEBUG handle_message] calling run_job NOW", flush=True)
            await run_job(
                channel_id=job_channel_id,
                user_msg_id=message.id,
                text=prompt,
                resume_token=resume_token,
                context=run_context,
                thread_id=thread_id,
                reply_ref=reply_ref,
                guild_id=guild_id,
            )
        except Exception:
            logger.exception("handle_message.run_job_failed")

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

    # Auto-join new threads so we receive messages from them
    @cfg.bot.client.event
    async def on_thread_create(thread: discord.Thread) -> None:
        with contextlib.suppress(discord.HTTPException):
            await thread.join()
            logger.debug("thread.auto_joined", thread_id=thread.id, name=thread.name)

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
