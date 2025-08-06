import asyncio
import re

import aiohttp
import discord
from discord import *
from discord.ext import commands

from config import GITHUB_PAT_DOCS


class RepoDetails:
    GITHUB_TOKEN = GITHUB_PAT_DOCS
    OWNER = "Marvel-Discord"
    REPO = "marvel-discord-docs"
    BRANCH = "main"

    GITHUB_RAW_BASE = (
        f"https://raw.githubusercontent.com/{OWNER}/{REPO}/refs/heads/{BRANCH}"
    )

    HEADERS = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }


async def fetch(session, query):
    """Makes an asynchronous request to GitHub GraphQL API."""
    async with session.post(
        "https://api.github.com/graphql",
        json={"query": query},
        headers=RepoDetails.HEADERS,
    ) as response:
        return await response.json()


async def get_files_in_folder(session, path=""):
    """Recursively retrieves all Markdown (.md) files in the repository."""
    query = f"""
    query {{
      repository(owner: "{RepoDetails.OWNER}", name: "{RepoDetails.REPO}") {{
        object(expression: "{RepoDetails.BRANCH}:{path}") {{
          ... on Tree {{
            entries {{
              name
              type
              path
            }}
          }}
        }}
      }}
    }}
    """
    data = await fetch(session, query)

    if "errors" in data:
        print("Error:", data["errors"])
        return []

    files = []
    if data["data"]["repository"]["object"]:
        for entry in data["data"]["repository"]["object"]["entries"]:
            if entry["type"] == "blob" and entry["name"].endswith(".md"):
                files.append(entry["path"])
            elif entry["type"] == "tree":
                files.extend(
                    await get_files_in_folder(session, entry["path"])
                )  # Recursively process subfolders
    return files


async def get_file_content(session, file_path):
    """Fetches the content of a specific file asynchronously."""
    query = f"""
    query {{
      repository(owner: "{RepoDetails.OWNER}", name: "{RepoDetails.REPO}") {{
        object(expression: "{RepoDetails.BRANCH}:{file_path}") {{
          ... on Blob {{
            text
          }}
        }}
      }}
    }}
    """
    data = await fetch(session, query)

    if "errors" in data:
        print(f"Error fetching {file_path}:", data["errors"])
        return None

    return data["data"]["repository"]["object"]["text"]


async def search_in_files(search_string: str) -> dict[str, str]:
    """Finds all `.md` files and checks for the target string asynchronously."""
    async with aiohttp.ClientSession() as session:
        md_files = await get_files_in_folder(session)

        # Fetch file contents in parallel
        tasks = [get_file_content(session, file) for file in md_files]
        contents = await asyncio.gather(*tasks)

        # Find matches
        matching_files = {
            file: content
            for file, content in zip(md_files, contents)
            if content and search_string in content
        }

        return matching_files


async def search_for_channel_in_docs(channel: discord.TextChannel) -> dict[str, str]:
    return await search_in_files(f"discord-channel-id: {channel.id}")


async def search_for_all_channels_in_docs() -> dict[str, str]:
    return await search_in_files("discord-channel-id:")


def convert_md_images(md_string):
    def image_replacer(match):
        alt_text, image_path = match.groups()

        if image_path.startswith("http"):
            return match.group(0)

        else:
            # Remove leading `../../../` to construct the raw URL correctly
            clean_path = image_path.lstrip("../")

            # Construct the final GitHub raw URL
            github_url = f"{RepoDetails.GITHUB_RAW_BASE}/{clean_path}"

            return github_url

    # Regex to match image Markdown syntax
    return re.sub(r"!\[(.*?)\]\((.*?)\)", image_replacer, md_string)


def format_message(message: str) -> str:
    # Convert @user mentions
    message = re.sub(r"\@\[(.*?)\]\((\d+)\)", r"<@\2>", message)

    # Convert @role mentions
    message = re.sub(r"\@\&\[(.*?)\]\((\d+)\)", r"<@&\2>", message)

    # Convert #channel mentions
    message = re.sub(r"\#\[(.*?)\]\((\d+)\)", r"<#\2>", message)

    # Convert !url mentions
    message = re.sub(r"\!(https?:\/\/[^\s)]+)", r"<\1>", message)

    # Convert images
    message = convert_md_images(message)

    return message


def identify_discord_channel_id(message: str) -> int:
    # Extract the Discord channel ID from the message
    match = re.search(r"discord-channel-id: (\d+)", message)
    if match:
        return int(match.group(1))
    return None


def process_file_content(content: str) -> list[str]:
    messages = [i.strip() for i in content.split("---")[3:] if i]

    formatted_messages = [format_message(message) for message in messages]

    if any(len(message) > 2000 for message in formatted_messages):
        raise ValueError

    return formatted_messages


class DocsCog(discord.ext.commands.Cog, name="Docs"):
    """Docs commands"""

    def __init__(self, bot):
        self.bot = bot

    async def send_messages(
        self, files: dict[str, str], current_channel: discord.TextChannel
    ):
        doc_messages = []
        for file_path, content in files.items():
            doc_messages.extend(process_file_content(content))

        await current_channel.purge(
            limit=100, check=lambda m: m.author == self.bot.user
        )

        for message in doc_messages:
            if message:
                await current_channel.send(
                    message, allowed_mentions=AllowedMentions.none()
                )

        return len(doc_messages)

    @app_commands.command(name="sync-channel-doc")
    @commands.has_permissions(manage_messages=True)
    async def sync_channel_doc(
        self, interaction: discord.Interaction, all: bool = False
    ):
        """Sync the channel's messages to the docs"""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not all:
            current_channel = interaction.channel

            files = await search_for_channel_in_docs(current_channel)

            try:
                message_count = await self.send_messages(files, current_channel)

            except ValueError:
                return await interaction.followup.send(
                    "One of the messages is too long (max 2000 characters). Please check the file.",
                    ephemeral=True,
                )

            await interaction.followup.send(
                f"Synced {message_count} messages to {current_channel.mention}",
                ephemeral=True,
            )

        else:
            all_channels = await search_for_all_channels_in_docs()

            files_by_channel: dict[int, dict[str, str]] = {}

            for file, file_content in all_channels.items():
                channel_id = identify_discord_channel_id(file_content)
                if channel_id:
                    if channel_id not in files_by_channel:
                        files_by_channel[channel_id] = {file: file_content}
                    files_by_channel[channel_id][file] = file_content

            tally: dict[discord.TextChannel, int] = {}

            for channel_id, files in files_by_channel.items():
                channel = self.bot.get_channel(channel_id)
                if channel:
                    try:
                        tally[channel] = await self.send_messages(files, channel)

                    except ValueError:
                        tally[channel] = -1

            await interaction.followup.send(
                "Synced channels:\n"
                + "\n".join(
                    [
                        (
                            f"- {count} messages in {channel.mention}"
                            if count > 0
                            else f"- {channel.mention} has a message too long (max 2000 characters)"
                        )
                        for channel, count in tally.items()
                    ]
                ),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(DocsCog(bot))
