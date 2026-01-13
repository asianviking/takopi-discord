"""Category/channel to project/branch mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from .types import DiscordChannelContext

if TYPE_CHECKING:
    from .client import DiscordBotClient

# Channel naming conventions
MAIN_BRANCH_NAMES = {"main", "master"}
ISSUE_PATTERN = re.compile(r"^issue-(\d+)(?:-(.+))?$")
FEAT_PATTERN = re.compile(r"^feat-(.+)$")


@dataclass(frozen=True, slots=True)
class ChannelMapping:
    """Mapping of a Discord channel to a project/branch."""

    guild_id: int
    category_id: int | None
    category_name: str | None
    channel_id: int
    channel_name: str
    project: str | None
    branch: str


def infer_branch_from_channel_name(channel_name: str) -> str:
    """Infer the git branch name from a Discord channel name.

    Channel naming conventions:
    - #main or #master -> main/master branch
    - #issue-NNN or #issue-NNN-description -> issue-NNN or issue-NNN-description
    - #feat-name -> feat-name or feat/name
    - Other -> use channel name as-is
    """
    name = channel_name.lower().strip()

    # Main/master branches
    if name in MAIN_BRANCH_NAMES:
        return name

    # Issue branches: issue-123 or issue-123-fix-bug
    issue_match = ISSUE_PATTERN.match(name)
    if issue_match:
        issue_num = issue_match.group(1)
        description = issue_match.group(2)
        if description:
            return f"issue-{issue_num}-{description}"
        return f"issue-{issue_num}"

    # Feature branches: feat-name
    feat_match = FEAT_PATTERN.match(name)
    if feat_match:
        return f"feat-{feat_match.group(1)}"

    # Default: use channel name as branch
    return name


def infer_project_from_category_name(category_name: str) -> str:
    """Infer the project name from a Discord category name.

    Converts to lowercase and replaces spaces with hyphens.
    """
    return category_name.lower().strip().replace(" ", "-")


class CategoryChannelMapper:
    """Maps Discord categories and channels to projects and branches."""

    def __init__(self, bot: DiscordBotClient) -> None:
        self._bot = bot

    def get_channel_mapping(
        self,
        guild_id: int,
        channel_id: int,
    ) -> ChannelMapping | None:
        """Get the mapping for a channel."""
        channel = self._bot.get_channel(channel_id)
        if channel is None:
            return None

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None

        # For threads, get the parent channel
        if isinstance(channel, discord.Thread):
            parent = channel.parent
            if parent is None or not isinstance(parent, discord.TextChannel):
                return None
            channel = parent

        category = channel.category
        category_id = category.id if category else None
        category_name = category.name if category else None

        # Infer project from category name if available
        project = None
        if category_name is not None:
            project = infer_project_from_category_name(category_name)

        # Infer branch from channel name
        branch = infer_branch_from_channel_name(channel.name)

        return ChannelMapping(
            guild_id=guild_id,
            category_id=category_id,
            category_name=category_name,
            channel_id=channel.id,
            channel_name=channel.name,
            project=project,
            branch=branch,
        )

    def get_context_from_mapping(
        self,
        mapping: ChannelMapping,
        *,
        default_project: str | None = None,
    ) -> DiscordChannelContext | None:
        """Convert a channel mapping to a context.

        Args:
            mapping: The channel mapping
            default_project: Default project if category doesn't map to one
        """
        project = mapping.project or default_project
        if project is None:
            return None
        return DiscordChannelContext(project=project, branch=mapping.branch)

    def list_category_channels(
        self,
        guild_id: int,
        category_id: int,
    ) -> list[ChannelMapping]:
        """List all channels in a category."""
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return []

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return []

        mappings: list[ChannelMapping] = []
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                branch = infer_branch_from_channel_name(channel.name)
                project = infer_project_from_category_name(category.name)
                mappings.append(
                    ChannelMapping(
                        guild_id=guild_id,
                        category_id=category_id,
                        category_name=category.name,
                        channel_id=channel.id,
                        channel_name=channel.name,
                        project=project,
                        branch=branch,
                    )
                )
        return mappings
