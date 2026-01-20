"""Main event loop for Discord transport."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, cast

import anyio
import discord

from takopi.logging import get_logger
from takopi.markdown import MarkdownParts
from takopi.model import ResumeToken
from takopi.runner_bridge import RunningTasks
from takopi.runners.run_options import EngineRunOptions, apply_run_options
from takopi.transport import MessageRef, RenderedMessage

from .bridge import CANCEL_BUTTON_ID, DiscordBridgeConfig, DiscordTransport
from .commands import discover_command_ids, register_plugin_commands
from .handlers import (
    extract_prompt_from_message,
    is_bot_mentioned,
    parse_branch_prefix,
    register_engine_commands,
    register_slash_commands,
    should_process_message,
)
from .overrides import resolve_overrides, resolve_trigger_mode
from .render import prepare_discord
from .state import DiscordStateStore
from .types import DiscordChannelContext, DiscordThreadContext

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
    _ = cast(DiscordTransport, cfg.exec_cfg.transport)  # Used for type checking only

    # Initialize voice manager if OpenAI API key is available (needed for TTS)
    # STT uses local Whisper via pywhispercpp
    voice_manager = None
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        try:
            from openai import AsyncOpenAI

            from .voice import WHISPER_MODEL, VoiceManager

            openai_client = AsyncOpenAI(api_key=openai_api_key)
            whisper_model = os.environ.get("WHISPER_MODEL", WHISPER_MODEL)
            voice_manager = VoiceManager(
                cfg.bot, openai_client, whisper_model=whisper_model
            )
            logger.info("voice.enabled", whisper_model=whisper_model)
        except ImportError as e:
            logger.warning("voice.disabled", reason=f"missing package: {e}")
    else:
        logger.info("voice.disabled", reason="OPENAI_API_KEY not set (needed for TTS)")

    logger.info(
        "loop.config",
        has_state_store=state_store is not None,
        guild_id=cfg.guild_id,
        voice_enabled=voice_manager is not None,
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

    # Register built-in slash commands (reserved commands)
    register_slash_commands(
        cfg.bot,
        state_store=state_store,
        get_running_task=get_running_task,
        cancel_task=cancel_task,
        runtime=cfg.runtime,
        upload_dir=cfg.upload_dir,
        voice_manager=voice_manager,
    )

    # Register dynamic engine commands (/claude, /codex, etc.)
    engine_commands = register_engine_commands(
        cfg.bot,
        cfg=cfg,
        state_store=state_store,
        running_tasks=running_tasks,
        default_engine_override=default_engine_override,
    )
    if engine_commands:
        logger.info(
            "engine_commands.registered",
            count=len(engine_commands),
            commands=sorted(engine_commands),
        )

    # Discover and register plugin commands
    command_ids = discover_command_ids(cfg.runtime.allowlist)
    if command_ids:
        logger.info(
            "plugins.discovered",
            count=len(command_ids),
            ids=sorted(command_ids),
        )
        register_plugin_commands(
            cfg.bot,
            cfg,
            command_ids=command_ids,
            running_tasks=running_tasks,
            state_store=state_store,
            default_engine_override=default_engine_override,
        )
    else:
        logger.info("plugins.none_found")

    async def run_job(
        channel_id: int,
        user_msg_id: int,
        text: str,
        resume_token: ResumeToken | None,
        context: RunContext | None,
        thread_id: int | None = None,
        reply_ref: MessageRef | None = None,
        guild_id: int | None = None,
        run_options: EngineRunOptions | None = None,
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
                        token_preview=new_token.value[:20] + "..."
                        if len(new_token.value) > 20
                        else new_token.value,
                    )
                    if state_store and guild_id:
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
                        )

                with apply_run_options(run_options):
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
        logger.debug(
            "message.raw",
            channel_type=type(message.channel).__name__,
            channel_id=message.channel.id,
            author=message.author.name,
            content_preview=message.content[:50] if message.content else "",
        )

        # Guild-only: ignore DMs
        if message.guild is None:
            logger.debug("message.skipped", reason="not in guild (DM)")
            return

        if not should_process_message(message, cfg.bot.user, require_mention=False):
            logger.debug(
                "message.skipped", reason="should_process_message returned False"
            )
            return

        channel_id = message.channel.id
        guild_id = message.guild.id
        thread_id = None
        is_new_thread = False

        # Auto-set startup channel on first interaction (if not already set)
        if state_store and not isinstance(message.channel, discord.Thread):
            current_startup = await state_store.get_startup_channel(guild_id)
            if current_startup is None:
                await state_store.set_startup_channel(guild_id, channel_id)
                logger.info(
                    "startup_channel.auto_set",
                    guild_id=guild_id,
                    channel_id=channel_id,
                )

        # Check if this is a thread
        if isinstance(message.channel, discord.Thread):
            thread_id = message.channel.id
            parent = message.channel.parent
            if parent:
                channel_id = parent.id
            logger.debug(
                "message.in_thread",
                thread_id=thread_id,
                parent_channel_id=channel_id,
            )
            # Ensure we're a member of the thread so we receive future messages
            with contextlib.suppress(discord.HTTPException):
                await message.channel.join()

        # Get context from state
        # For threads, check thread-specific context first (set via @branch prefix)
        # Thread context has a specific branch; channel context uses worktree_base
        channel_context: DiscordChannelContext | None = None
        thread_context: DiscordThreadContext | None = None

        if state_store and guild_id:
            if thread_id:
                # Check if thread has its own bound context (from @branch prefix)
                ctx = await state_store.get_context(guild_id, thread_id)
                if isinstance(ctx, DiscordThreadContext):
                    thread_context = ctx

            # Always get channel context for project info and defaults
            ctx = await state_store.get_context(guild_id, channel_id)
            if isinstance(ctx, DiscordChannelContext):
                channel_context = ctx

        # Check trigger mode - may skip processing if mentions-only and not mentioned
        trigger_mode = await resolve_trigger_mode(
            state_store, guild_id, channel_id, thread_id
        )
        if trigger_mode == "mentions":
            # Check if bot is mentioned or if this is a reply to the bot
            bot_mentioned = is_bot_mentioned(message, cfg.bot.user)
            is_reply_to_bot = False
            if message.reference and message.reference.message_id:
                # Check if replying to a bot message
                try:
                    ref_msg = await message.channel.fetch_message(
                        message.reference.message_id
                    )
                    is_reply_to_bot = ref_msg.author == cfg.bot.user
                except discord.NotFound:
                    pass
            if not bot_mentioned and not is_reply_to_bot:
                logger.debug(
                    "message.skipped",
                    reason="trigger_mode=mentions, bot not mentioned or replied to",
                )
                return

        # Determine effective context: thread context takes priority, otherwise use channel's worktree_base
        run_context: RunContext | None = None
        if thread_context:
            from takopi.context import RunContext

            run_context = RunContext(
                project=thread_context.project,
                branch=thread_context.branch,
            )
        elif channel_context:
            from takopi.context import RunContext

            # Use worktree_base as the default branch when no @branch specified
            run_context = RunContext(
                project=channel_context.project,
                branch=channel_context.worktree_base,
            )

        # Extract prompt
        prompt = extract_prompt_from_message(message, cfg.bot.user)

        # Parse @branch prefix (only for new messages in channels, not in existing threads)
        branch_override: str | None = None
        if thread_id is None:
            branch_override, prompt = parse_branch_prefix(prompt)
            if branch_override:
                logger.info("branch.override", branch=branch_override)

        # Allow empty prompt if @branch was used (thread will be created for future prompts)
        if not prompt.strip() and not branch_override:
            return

        # Apply branch override to context
        if branch_override:
            from takopi.context import RunContext

            if channel_context:
                # Override branch but keep project from channel
                run_context = RunContext(
                    project=channel_context.project,
                    branch=branch_override,
                )
            else:
                # No project bound - require /bind first
                logger.warning(
                    "branch.no_project",
                    branch=branch_override,
                    channel_id=channel_id,
                )
                await message.reply(
                    f"Cannot use `@{branch_override}` - this channel has no project bound.\n"
                    "Use `/bind <project>` first to bind this channel to a project.",
                    mention_author=False,
                )
                return

        # Create thread for the response if not already in a thread
        if thread_id is None and isinstance(message.channel, discord.TextChannel):
            # Thread name is just the branch if @branch was used, otherwise prompt snippet
            if branch_override:
                thread_name = branch_override
            else:
                thread_name = (
                    prompt[:100] if len(prompt) <= 100 else prompt[:97] + "..."
                )
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

                # Save thread context if @branch was used
                if branch_override and state_store and guild_id and channel_context:
                    new_thread_context = DiscordThreadContext(
                        project=channel_context.project,
                        branch=branch_override,
                        worktrees_dir=channel_context.worktrees_dir,
                        default_engine=channel_context.default_engine,
                    )
                    await state_store.set_context(
                        guild_id, thread_id, new_thread_context
                    )
                    logger.info(
                        "thread.context_saved",
                        thread_id=thread_id,
                        project=channel_context.project,
                        branch=branch_override,
                    )

                    # If @branch was used without a prompt, send confirmation and return
                    if not prompt.strip():
                        thread_channel = cfg.bot.bot.get_channel(thread_id)
                        if thread_channel and isinstance(
                            thread_channel, discord.Thread
                        ):
                            await thread_channel.send(
                                f"Thread bound to branch `{branch_override}`. "
                                "Send a message here to start prompting."
                            )
                        logger.info(
                            "branch.thread_only",
                            thread_id=thread_id,
                            branch=branch_override,
                        )
                        return

        # Get resume token to maintain conversation continuity
        # For threads, use thread_id as the session key to maintain conversation continuity
        # within the thread (regardless of which specific message is being replied to)
        resume_token: ResumeToken | None = None
        session_key = thread_id if thread_id else channel_id
        logger.debug(
            "session.lookup",
            guild_id=guild_id,
            session_key=session_key,
            has_state_store=state_store is not None,
        )

        # Get engine_id from context (thread or channel), fallback to config
        if thread_context:
            engine_id = thread_context.default_engine
        elif channel_context:
            engine_id = channel_context.default_engine
        else:
            engine_id = cfg.runtime.default_engine or "claude"

        if state_store and guild_id:
            token_str = await state_store.get_session(guild_id, session_key, engine_id)
            if token_str:
                resume_token = ResumeToken(engine=engine_id, value=token_str)
                logger.info(
                    "session.restored",
                    guild_id=guild_id,
                    session_key=session_key,
                    engine_id=engine_id,
                    token_preview=token_str[:20] + "..."
                    if len(token_str) > 20
                    else token_str,
                )
            else:
                logger.debug(
                    "session.not_found",
                    guild_id=guild_id,
                    session_key=session_key,
                    engine_id=engine_id,
                )

        # For new threads, don't set reply_ref since the original message is in the parent channel
        # and runner_bridge creates its own user_ref that would be incorrect for cross-channel replies
        reply_ref: MessageRef | None = None
        if not is_new_thread:
            reply_ref = MessageRef(
                channel_id=channel_id,
                message_id=message.id,
                thread_id=thread_id,
            )

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

        # Resolve model and reasoning overrides
        overrides = await resolve_overrides(
            state_store, guild_id, channel_id, thread_id, engine_id
        )
        run_options: EngineRunOptions | None = None
        if overrides.model or overrides.reasoning:
            run_options = EngineRunOptions(
                model=overrides.model,
                reasoning=overrides.reasoning,
            )
            logger.debug(
                "run_options.resolved",
                model=overrides.model,
                model_source=overrides.source_model,
                reasoning=overrides.reasoning,
                reasoning_source=overrides.source_reasoning,
            )

        try:
            await run_job(
                channel_id=job_channel_id,
                user_msg_id=message.id,
                text=prompt,
                resume_token=resume_token,
                context=run_context,
                thread_id=thread_id,
                reply_ref=reply_ref,
                guild_id=guild_id,
                run_options=run_options,
            )
        except Exception:
            logger.exception("handle_message.run_job_failed")

    # Set up message handler
    cfg.bot.set_message_handler(handle_message)

    # Handle cancel button interactions
    @cfg.bot.bot.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        # Handle component interactions (buttons)
        if interaction.type == discord.InteractionType.component:
            if interaction.data:
                custom_id = interaction.data.get("custom_id")
                if custom_id == CANCEL_BUTTON_ID:
                    # Get the channel where the cancel was clicked
                    channel_id = interaction.channel_id
                    if channel_id is not None:
                        await cancel_task(channel_id)
                    await interaction.response.defer()
            return

        # For application commands, let Pycord handle them
        # This is required when overriding on_interaction
        await cfg.bot.bot.process_application_commands(interaction)

    # Auto-join new threads so we receive messages from them
    @cfg.bot.bot.event
    async def on_thread_create(thread: discord.Thread) -> None:
        with contextlib.suppress(discord.HTTPException):
            await thread.join()
            logger.debug("thread.auto_joined", thread_id=thread.id, name=thread.name)

    # Handle voice state updates (users joining/leaving voice channels)
    if voice_manager is not None:

        @cfg.bot.bot.event
        async def on_voice_state_update(
            member: discord.Member,
            before: discord.VoiceState,
            after: discord.VoiceState,
        ) -> None:
            await voice_manager.handle_voice_state_update(member, before, after)

        # Set up voice message handler
        async def handle_voice_message(
            guild_id: int,
            text_channel_id: int,
            transcript: str,
            user_name: str,
            project: str,
            branch: str,
        ) -> str | None:
            """Handle a transcribed voice message.

            Routes through Claude/takopi for full conversation context.
            Says "Working on it" immediately, then TTS the final response.
            """
            from takopi.context import RunContext

            logger.info(
                "voice.message",
                guild_id=guild_id,
                text_channel_id=text_channel_id,
                user_name=user_name,
                transcript_length=len(transcript),
            )

            # Post the transcribed message to the text channel
            transport = cast(DiscordTransport, cfg.exec_cfg.transport)
            await transport.send(
                channel_id=text_channel_id,
                message=RenderedMessage(
                    text=f"🎤 **{user_name}**: {transcript}",
                    extra={},
                ),
            )

            # Say "Working on it" via TTS immediately
            # Return this first, then process through Claude
            # The final response will be captured via message listener

            # Set up a listener to capture the final response for TTS
            final_response: list[str] = []
            response_event = anyio.Event()

            async def on_message(channel_id: int, text: str, is_final: bool) -> None:
                if is_final and text:
                    # Extract just the answer text from the formatted message
                    # The format is typically: header + answer + footer
                    # We want just the main content for TTS
                    final_response.append(text)
                    response_event.set()

            # Register the listener
            transport.add_message_listener(text_channel_id, on_message)

            try:
                # Build run context
                run_context = RunContext(project=project, branch=branch)

                # Get resume token for the text channel
                resume_token: ResumeToken | None = None
                engine_id = cfg.runtime.default_engine or "claude"
                token_str = await state_store.get_session(
                    guild_id, text_channel_id, engine_id
                )
                if token_str:
                    resume_token = ResumeToken(engine=engine_id, value=token_str)

                # Use run_job to process the voice message through Claude
                import time

                voice_msg_id = int(time.time() * 1000)

                # Run the job (this will send progress updates and final response)
                await run_job(
                    channel_id=text_channel_id,
                    user_msg_id=voice_msg_id,
                    text=transcript,
                    resume_token=resume_token,
                    context=run_context,
                    thread_id=None,
                    reply_ref=None,
                    guild_id=guild_id,
                )

                # Wait briefly for the final response to be captured
                with anyio.move_on_after(5.0):
                    await response_event.wait()

                if final_response:
                    # Extract a TTS-friendly summary from the response
                    response_text = final_response[0]

                    # Strip markdown formatting for cleaner TTS
                    import re

                    # Remove the first line (status line like "✅ done · claude · 10s")
                    lines = response_text.split("\n")
                    response_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
                    # Remove code blocks
                    response_text = re.sub(r"```[\s\S]*?```", "", response_text)
                    # Remove inline code
                    response_text = re.sub(r"`[^`]+`", "", response_text)
                    # Remove bold/italic markers
                    response_text = re.sub(r"\*+([^*]+)\*+", r"\1", response_text)
                    # Remove headers
                    response_text = re.sub(
                        r"^#+\s+", "", response_text, flags=re.MULTILINE
                    )
                    # Remove resume lines (e.g., "↩️ resume: ...")
                    response_text = re.sub(
                        r"^↩️.*$", "", response_text, flags=re.MULTILINE
                    )
                    # Clean up whitespace
                    response_text = re.sub(r"\n{3,}", "\n\n", response_text).strip()

                    # Truncate for TTS if too long (keep first ~500 chars)
                    if len(response_text) > 500:
                        response_text = response_text[:500] + "..."

                    # Skip if nothing meaningful left after stripping
                    if not response_text or len(response_text) < 5:
                        return None

                    logger.info(
                        "voice.response",
                        guild_id=guild_id,
                        response_length=len(response_text),
                    )

                    return response_text

            except Exception:
                logger.exception("voice.response_error")

            finally:
                # Clean up the listener
                transport.remove_message_listener(text_channel_id)

            return None

        voice_manager.set_message_handler(handle_voice_message)

    # Start the bot
    await cfg.bot.start()

    # Send startup message to configured channel or first available text channel
    if cfg.guild_id:
        startup_channel_id = await state_store.get_startup_channel(cfg.guild_id)
        if startup_channel_id:
            await _send_startup(cfg, startup_channel_id)
            logger.info("startup.configured_channel", channel_id=startup_channel_id)
        else:
            guild = cfg.bot.get_guild(cfg.guild_id)
            if guild:
                for channel in guild.text_channels:
                    await _send_startup(cfg, channel.id)
                    logger.info(
                        "startup.first_channel",
                        channel_id=channel.id,
                        hint="mention bot in preferred channel to set as startup channel",
                    )
                    break

    logger.info("bot.ready", user=cfg.bot.user.name if cfg.bot.user else "unknown")

    # Keep running until cancelled
    try:
        await anyio.sleep_forever()
    finally:
        await cfg.bot.close()
