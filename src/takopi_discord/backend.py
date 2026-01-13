"""Discord transport backend for takopi."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio

from takopi.backends import EngineBackend
from takopi.logging import get_logger
from takopi.runner_bridge import ExecBridgeConfig
from takopi.transport_runtime import TransportRuntime
from takopi.transports import SetupResult, TransportBackend

from .bridge import DiscordBridgeConfig, DiscordPresenter, DiscordTransport
from .client import DiscordBotClient
from .loop import run_main_loop
from .onboarding import check_setup, interactive_setup

logger = get_logger(__name__)

__all__ = ["BACKEND", "DiscordBackend"]


def _get_discord_settings(transport_config: object) -> dict[str, Any]:
    """Extract Discord settings from transport config.

    Since Discord is a plugin, settings come as a dict from model_extra.
    """
    if isinstance(transport_config, dict):
        return transport_config
    # Try to convert pydantic model to dict
    if hasattr(transport_config, "model_dump"):
        return transport_config.model_dump()
    raise TypeError(f"unexpected transport_config type: {type(transport_config)}")


def _build_startup_message(
    runtime: TransportRuntime,
    *,
    startup_pwd: str,
) -> str:
    """Build the startup message displayed when bot connects."""
    available_engines = list(runtime.available_engine_ids())
    missing_engines = list(runtime.missing_engine_ids())
    misconfigured_engines = list(runtime.engine_ids_with_status("bad_config"))
    failed_engines = list(runtime.engine_ids_with_status("load_error"))

    engine_list = ", ".join(available_engines) if available_engines else "none"

    notes: list[str] = []
    if missing_engines:
        notes.append(f"not installed: {', '.join(missing_engines)}")
    if misconfigured_engines:
        notes.append(f"misconfigured: {', '.join(misconfigured_engines)}")
    if failed_engines:
        notes.append(f"failed to load: {', '.join(failed_engines)}")
    if notes:
        engine_list = f"{engine_list} ({'; '.join(notes)})"

    project_aliases = sorted(set(runtime.project_aliases()), key=str.lower)
    project_list = ", ".join(project_aliases) if project_aliases else "none"

    return (
        f"\N{OCTOPUS} **takopi-discord is ready**\n\n"
        f"default: `{runtime.default_engine}`  \n"
        f"agents: `{engine_list}`  \n"
        f"projects: `{project_list}`  \n"
        f"working in: `{startup_pwd}`"
    )


class DiscordBackend(TransportBackend):
    """Discord transport backend implementation."""

    id = "discord"
    description = "Discord bot"

    def check_setup(
        self,
        engine_backend: EngineBackend,
        *,
        transport_override: str | None = None,
    ) -> SetupResult:
        return check_setup(engine_backend, transport_override=transport_override)

    def interactive_setup(self, *, force: bool) -> bool:
        return interactive_setup(force=force)

    def lock_token(
        self, *, transport_config: object, _config_path: Path
    ) -> str | None:
        settings = _get_discord_settings(transport_config)
        return settings.get("bot_token")

    def build_and_run(
        self,
        *,
        transport_config: object,
        config_path: Path,
        runtime: TransportRuntime,
        final_notify: bool,
        default_engine_override: str | None,
    ) -> None:
        settings = _get_discord_settings(transport_config)
        token = settings["bot_token"]
        guild_id = settings.get("guild_id")
        message_overflow = settings.get("message_overflow", "trim")
        session_mode = settings.get("session_mode", "stateless")
        show_resume_line = settings.get("show_resume_line", True)

        startup_msg = _build_startup_message(
            runtime,
            startup_pwd=os.getcwd(),
        )

        bot = DiscordBotClient(token, guild_id=guild_id)
        transport = DiscordTransport(bot)
        presenter = DiscordPresenter(message_overflow=message_overflow)
        exec_cfg = ExecBridgeConfig(
            transport=transport,
            presenter=presenter,
            final_notify=final_notify,
        )
        cfg = DiscordBridgeConfig(
            bot=bot,
            runtime=runtime,
            guild_id=guild_id,
            startup_msg=startup_msg,
            exec_cfg=exec_cfg,
            session_mode=session_mode,
            show_resume_line=show_resume_line,
            message_overflow=message_overflow,
        )

        async def run_loop() -> None:
            await run_main_loop(
                cfg,
                default_engine_override=default_engine_override,
            )

        anyio.run(run_loop)


discord_backend = DiscordBackend()
BACKEND = discord_backend
