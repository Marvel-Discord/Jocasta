from discord.ext import commands
from discord import Embed
import config

import datetime
import io
import traceback
from functools import partial

import aiohttp
import discord
from discord import *
from requests import HTTPError

from config import *

import tmdbsimple as tmdb

class SpoilerThreadCog(commands.Cog) :
    def __init__(self, bot) :
        self.bot = bot

        tmdb.API_KEY = TMDB_KEY
        self.search = tmdb.Search()
        
        self.request_spoiler_thread_id = config.request_spoiler_thread_channel
    
        # Sticky messages
        self.thread_request_embed = Embed(
            title="**Request Spoiler Threads**",
            description=(
                "Here you can request spoiler threads about new movies/shows/games! Simply state the title of whatever you want a thread for.\n\n" 
                "Please ***only*** request a thread for recent releases or stuff that will release soon. Please ***only*** request a thread if you **intend to use it!**"
            ),
        )



    @commands.Cog.listener()
    async def on_message(self, message) :
        """Checks for new messages in the spoiler thread request channel."""
        if message.author.bot :
            if message.author == self.bot.user and message.embeds :
                embed = message.embeds[0]
                if embed.title == self.thread_request_embed.title :
                    return
        
        if message.channel.id != self.request_spoiler_thread_id :
            return   
        
        # Remove previous embed messages from bot to keep latest at bottom (only if message embed title matches sticky message title)
        async for msg in message.channel.history(limit=5) :
            if msg.author == self.bot.user and msg.embeds :
                embed = msg.embeds[0]
                if embed.title == self.thread_request_embed.title :
                    await msg.delete()
                    
        # Send sticky embeds at bottom
        await message.channel.send(embed=self.thread_request_embed)

    spoiler_threads = app_commands.Group(
        name="spoiler-thread",
        description="Add spoiler threads!",
        guild_ids=[homeserver],
        default_permissions=Permissions(manage_messages=True),
    )

    @spoiler_threads.command(name="movie")
    @app_commands.describe(title="Movie to search for.")
    async def st_movie(self, interaction: discord.Interaction, title: str):
        """Add a movie spoiler thread."""
        await self.add_spoiler_thread(interaction, title, "movie")

    @spoiler_threads.command(name="tv")
    @app_commands.describe(title="TV show to search for.")
    async def st_tv(self, interaction: discord.Interaction, title: str):
        """Add a TV show spoiler thread."""
        await self.add_spoiler_thread(interaction, title, "tv")

    async def find_title(self, title: str, medium: str, year: str = None):
        if medium == "movie":
            return await self.bot.loop.run_in_executor(
                None, partial(self.search.movie, query=title, year=year)
            )
        elif medium == "tv":
            return await self.bot.loop.run_in_executor(
                None, partial(self.search.tv, query=title, first_air_date_year=year)
            )
        else:
            return None

    async def add_spoiler_thread(
        self, interaction: discord.Interaction, title: str, medium: str
    ):
        response = await self.find_title(title, medium)
        if response is None:
            return
        if not response["results"]:
            response = await self.find_title(
                title, medium, year=str(datetime.datetime.now().year)
            )
        if not response["results"]:
            return await interaction.followup.send(f"`{title}` returned no results.")

        result = response["results"][0]
        try:
            if medium == "movie":
                project = await self.bot.loop.run_in_executor(
                    None, tmdb.Movies, result["id"]
                )
            elif medium == "tv":
                project = await self.bot.loop.run_in_executor(
                    None, tmdb.TV, result["id"]
                )
            else:
                return
        except HTTPError:
            return await interaction.followup.send(f"API Request Failed.")

        await self.bot.loop.run_in_executor(None, project.info)
        current_season = (
            next(
                (i for i in reversed(project.seasons) if i["overview"]),
                project.seasons[-1],
            )
            if medium == "tv"
            else None
        )

        name = project.original_title if medium == "movie" else project.name
        desc = (
            project.overview
            if medium == "movie" or not current_season["overview"]
            else current_season["overview"]
        )
        tagline = project.tagline
        poster = "https://www.themoviedb.org/t/p/original" + (
            project.poster_path if medium == "movie" else current_season["poster_path"]
        )

        # creds = await self.bot.loop.run_in_executor(None, project.credits)

        items = {
            "title": discord.ui.TextInput(
                label="Title", placeholder="Type the title here...", default=name
            ),
            "description": discord.ui.TextInput(
                label="Description",
                placeholder="Type the description here...",
                default=desc,
                style=discord.TextStyle.long,
                required=False,
            ),
            "tagline": discord.ui.TextInput(
                label="Tagline",
                placeholder="Type the tagline here...",
                default=tagline,
                required=False,
            ),
            "poster": discord.ui.TextInput(
                label="Poster",
                placeholder="Type the poster URL here...",
                default=poster,
                required=False,
            ),
        }
        modal = self.EditModal(title="Create Spoiler Thread", texts=items)

        await interaction.response.send_modal(modal)
        await modal.wait()

        name = modal.values["title"]
        desc = modal.values["description"]
        tagline = modal.values["tagline"]
        poster = modal.values["poster"]

        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(poster) as r:
                    poster_file = discord.File(
                        io.BytesIO(await r.read()), filename="poster.png"
                    )
        except Exception:
            poster_file = None

        forum: discord.ForumChannel = self.bot.get_channel(spoiler_thread_channel)

        tag = next(
            i
            for i in forum.available_tags
            if i.name == ("Film" if medium == "movie" else "TV Show")
        )

        thread = await forum.create_thread(
            name=name,
            content=(f"## *{tagline}* \n" if tagline else f"## *{name}* \n")
            + (f"> *{desc}*" if desc else ""),
            file=poster_file,
            applied_tags=[tag],
        )

        await interaction.followup.send(f"**{thread.thread.mention}** created!")

    class EditModal(discord.ui.Modal):
        def __init__(self, *, title, texts):
            super().__init__(title=title)

            self.interaction = None
            self.texts = texts
            self.values = {}

            for k, v in self.texts.items():
                self.add_item(v)

        async def on_submit(self, interaction: discord.Interaction):
            self.values = {k: str(v) for k, v in self.texts.items()}
            await interaction.response.defer()
            self.interaction = interaction

        async def on_error(
            self, interaction: discord.Interaction, error: Exception
        ) -> None:
            await interaction.response.send_message("Something broke!", ephemeral=True)
            traceback.print_tb(error.__traceback__)


            
async def setup(bot: commands.Bot) :
    await bot.add_cog(SpoilerThreadCog(bot))
