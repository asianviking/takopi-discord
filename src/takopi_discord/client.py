"""Discord API client wrapper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    MessageHandler = Callable[[discord.Message], Coroutine[Any, Any, None]]
    InteractionHandler = Callable[[discord.Interaction], Coroutine[Any, Any, None]]


@dataclass(frozen=True, slots=True)
class SentMessage:
    """Result of sending a message."""

    message_id: int
    channel_id: int
    thread_id: int | None = None


class DiscordBotClient:
    """Wrapper around discord.py client for takopi integration."""

    def __init__(self, token: str, *, guild_id: int | None = None) -> None:
        self._token = token
        self._guild_id = guild_id
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = False
        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)
        self._ready_event = asyncio.Event()
        self._message_handler: MessageHandler | None = None
        self._interaction_handler: InteractionHandler | None = None

        @self._client.event
        async def on_ready() -> None:
            self._ready_event.set()

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._client.user:
                return
            if self._message_handler is not None:
                await self._message_handler(message)

    @property
    def client(self) -> discord.Client:
        """Get the underlying discord.py client."""
        return self._client

    @property
    def tree(self) -> app_commands.CommandTree:
        """Get the command tree for slash commands."""
        return self._tree

    @property
    def user(self) -> discord.User | None:
        """Get the bot user."""
        return self._client.user

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Set the message handler."""
        self._message_handler = handler

    def set_interaction_handler(self, handler: InteractionHandler) -> None:
        """Set the interaction handler for non-command interactions."""
        self._interaction_handler = handler

    async def start(self) -> None:
        """Start the bot and wait until ready."""
        asyncio.create_task(self._client.start(self._token))
        await self._ready_event.wait()
        # Sync commands
        if self._guild_id is not None:
            guild = discord.Object(id=self._guild_id)
            self._tree.copy_global_to(guild=guild)
            await self._tree.sync(guild=guild)
        else:
            await self._tree.sync()

    async def close(self) -> None:
        """Close the bot connection."""
        await self._client.close()

    async def wait_until_ready(self) -> None:
        """Wait until the bot is ready."""
        await self._ready_event.wait()

    async def send_message(
        self,
        *,
        channel_id: int,
        content: str,
        reply_to_message_id: int | None = None,
        thread_id: int | None = None,
        view: discord.ui.View | None = None,
        embed: discord.Embed | None = None,
    ) -> SentMessage | None:
        """Send a message to a channel."""
        channel = self._client.get_channel(thread_id or channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(thread_id or channel_id)
            except discord.NotFound:
                return None

        if not isinstance(channel, discord.abc.Messageable):
            return None

        reference = None
        if reply_to_message_id is not None:
            reference = discord.MessageReference(
                message_id=reply_to_message_id,
                channel_id=channel_id,
            )

        try:
            kwargs: dict[str, Any] = {"content": content}
            if reference is not None:
                kwargs["reference"] = reference
            if view is not None:
                kwargs["view"] = view
            if embed is not None:
                kwargs["embed"] = embed

            message = await channel.send(**kwargs)
            return SentMessage(
                message_id=message.id,
                channel_id=message.channel.id,
                thread_id=thread_id,
            )
        except discord.HTTPException:
            return None

    async def edit_message(
        self,
        *,
        channel_id: int,
        message_id: int,
        content: str,
        view: discord.ui.View | None = None,
        embed: discord.Embed | None = None,
    ) -> SentMessage | None:
        """Edit an existing message."""
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                return None

        if not isinstance(channel, discord.abc.Messageable):
            return None

        try:
            message = await channel.fetch_message(message_id)
            kwargs: dict[str, Any] = {"content": content}
            if view is not None:
                kwargs["view"] = view
            if embed is not None:
                kwargs["embed"] = embed

            edited = await message.edit(**kwargs)
            return SentMessage(
                message_id=edited.id,
                channel_id=edited.channel.id,
            )
        except discord.HTTPException:
            return None

    async def delete_message(
        self,
        *,
        channel_id: int,
        message_id: int,
    ) -> bool:
        """Delete a message."""
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                return False

        if not isinstance(channel, discord.abc.Messageable):
            return False

        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
            return True
        except discord.HTTPException:
            return False

    async def create_thread(
        self,
        *,
        channel_id: int,
        message_id: int,
        name: str,
        auto_archive_duration: int = 1440,  # 24 hours
    ) -> int | None:
        """Create a thread from a message."""
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                return None

        if not isinstance(channel, discord.TextChannel):
            return None

        try:
            message = await channel.fetch_message(message_id)
            thread = await message.create_thread(
                name=name,
                auto_archive_duration=auto_archive_duration,
            )
            return thread.id
        except discord.HTTPException:
            return None

    def get_guild(self, guild_id: int) -> discord.Guild | None:
        """Get a guild by ID."""
        return self._client.get_guild(guild_id)

    def get_channel(self, channel_id: int) -> discord.abc.GuildChannel | None:
        """Get a channel by ID."""
        channel = self._client.get_channel(channel_id)
        if isinstance(channel, discord.abc.GuildChannel):
            return channel
        return None
