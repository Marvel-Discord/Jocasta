import datetime
import io
import traceback
from functools import partial

import aiohttp
import discord
from discord import *
from discord.ext import commands
from requests import HTTPError

from config import *

import tmdbsimple as tmdb


class MoviesCog(discord.ext.commands.Cog, name="Movies"):
    """Movie commands"""

    def __init__(self, bot):
        self.bot = bot

        self.casts = {}
        self.titles = {}

        tmdb.API_KEY = TMDB_KEY
        self.search = tmdb.Search()

        self.bot.loop.create_task(self.schedule_load_casts())

    async def schedule_load_casts(self):
        # await self.bot.loop.run_in_executor(None, self.load_casts)
        await self.load_casts()

    async def load_casts(self):
        print("Loading casts...")

        mcu = {
            "movies": [
                1726,
                1724,
                10138,
                10195,
                1771,
                24428,
                68721,
                76338,
                100402,
                118340,
                102899,
                99861,
                271110,
                283995,
                315635,
                284053,
                284054,
                299536,
                363088,
                299537,
                299534,
                429617,
                497698,
                566525,
                524434,
                634649,
                616037,
                453395,
                505642,
                640146,
                447365,
                609681,
                822119,
                986056,
                617127,
                533535,
                617126,
                1003596,
                969681,
                1003598,
                894205,
                774752,
                1030022,
                76122,
                76535,
                119569,
                211387,
                253980,
                758025,
                1010818,
            ],
            "shows": [
                1403,
                61550,
                68716,
                67466,
                66190,
                88987,
                61889,
                38472,
                62126,
                62127,
                62285,
                67178,
                85271,
                88396,
                84958,
                91363,
                88329,
                92749,
                92782,
                92783,
                114472,
                122226,
                114471,
                138501,
                138505,
                202555,
                198178,
                138502,
                241388,
            ],
        }

        projects = {}

        for m_id in mcu["movies"]:
            m = await self.bot.loop.run_in_executor(None, tmdb.Movies, m_id)
            i = await self.bot.loop.run_in_executor(None, m.info)
            # print(i['original_title'])
            self.titles[m.id] = i["original_title"]
            c = await self.bot.loop.run_in_executor(None, m.credits)
            projects[m.id] = c

        for tv_id in mcu["shows"]:
            m = await self.bot.loop.run_in_executor(None, tmdb.TV, tv_id)
            i = await self.bot.loop.run_in_executor(None, m.info)
            # print(i['name'])
            self.titles[m.id] = i["name"]
            c = await self.bot.loop.run_in_executor(None, m.credits)
            projects[m.id] = c

        for m, c in projects.items():
            for p in c["cast"]:
                id_ = p["id"]
                if id_ not in self.casts:
                    self.casts[id_] = {}
                if m not in self.casts[id_]:
                    self.casts[id_][m] = []
                self.casts[id_][m].append(f"~{p['character']}")

            for p in c["crew"]:
                id_ = p["id"]
                if id_ not in self.casts:
                    self.casts[id_] = {}
                if m not in self.casts[id_]:
                    self.casts[id_][m] = []
                self.casts[id_][m].append(p["job"])

        # print(self.titles)
        print("Successfully loaded casts.")

    mcu_connections = app_commands.Group(
        name="mcu-connections", description="See crossover cast to the MCU!"
    )

    async def loaded(self, interaction: discord.Interaction):
        if not self.casts:
            await interaction.response.send_message(
                "Database has not yet been loaded. Please wait a few moments.",
                ephemeral=True,
            )
            return False
        else:
            await interaction.response.defer()
            return True

    async def within(self, interaction, name, id_):
        if id_ in self.titles:
            await interaction.followup.send(f"`{name}` is in the MCU!")
        return id_ in self.titles

    def most_common(self, lst):
        lst.sort(key=lambda x: not x.startswith("~"))
        return max(set(lst), key=lst.count)

    def find_match(self, cast, selector):
        mcu = self.casts[cast["id"]]
        roles = [vv for k, v in mcu.items() for vv in v]
        role_in_mcu = self.most_common(roles)
        title = self.titles[next(k for k, v in mcu.items() if role_in_mcu in v)]
        role_in_mcu = role_in_mcu.strip("~")
        return f"- **{cast['name']}** - {cast[selector]} ~~\\|\\|~~ {role_in_mcu} ({title}{f', {len(mcu) - 1} more' if len(mcu) > 1 else ''})"

    def connections(self, name, creds):
        matched = {}

        for c in creds["cast"]:
            if c["id"] not in matched and c["id"] in self.casts:
                matched[c["id"]] = self.find_match(c, "character")

        txt = [f"## MCU Connections: *{name}*"] + list(matched.values())
        if not matched:
            txt.append("No cast connections found.")
        else:
            txt.append(f"Total = **{len(matched)}** matches.")

        embeds = []
        current_txt = ""
        for t in txt:
            if len(current_txt) + len(t) > 4000:
                embeds.append(discord.Embed(description=current_txt.strip()))
                current_txt = ""
            current_txt += t + "\n"
        embeds.append(discord.Embed(description=current_txt.strip()))

        embeds[-1].set_footer(
            text="Data sourced from TMDB. (Casting is sometimes incomplete on TV shows)"
        )

        return embeds

    @mcu_connections.command(name="movie")
    @app_commands.describe(movie="Movie to search for.")
    async def mc_movie(self, interaction: discord.Interaction, movie: str):
        """Shared cast between MCU and a movie."""
        if not await self.loaded(interaction):
            return

        response = await self.bot.loop.run_in_executor(
            None, partial(self.search.movie, query=movie)
        )
        if not response["results"]:
            return await interaction.followup.send(f"`{movie}` returned no results.")

        result = response["results"][0]
        try:
            project = await self.bot.loop.run_in_executor(
                None, tmdb.Movies, result["id"]
            )
        except HTTPError:
            return await interaction.followup.send(f"API Request Failed.")

        await self.bot.loop.run_in_executor(None, project.info)
        name = f"{project.original_title} ({project.release_date.split('-')[0]})"

        if await self.within(interaction, name, result["id"]):
            return

        creds = await self.bot.loop.run_in_executor(None, project.credits)

        try:
            await interaction.followup.send(embeds=self.connections(name, creds))
        except HTTPException:
            await interaction.followup.send("... the list is too long")

    @mcu_connections.command(name="tv")
    @app_commands.describe(tv_show="TV show to search for.")
    async def mc_tv(self, interaction: discord.Interaction, tv_show: str):
        """Shared cast between MCU and a TV show."""
        if not await self.loaded(interaction):
            return

        response = await self.bot.loop.run_in_executor(
            None, partial(self.search.tv, query=tv_show)
        )
        if not response["results"]:
            return await interaction.followup.send(f"`{tv_show}` returned no results.")

        result = response["results"][0]
        try:
            project = await self.bot.loop.run_in_executor(None, tmdb.TV, result["id"])
        except HTTPError:
            return await interaction.followup.send(f"API Request Failed.")

        await self.bot.loop.run_in_executor(None, project.info)
        name = f"{project.name} ({project.first_air_date.split('-')[0]})"

        if await self.within(interaction, name, result["id"]):
            return

        creds = await self.bot.loop.run_in_executor(None, project.credits)

        try:
            await interaction.followup.send(embeds=self.connections(name, creds))
        except HTTPException:
            await interaction.followup.send("... the list is too long")

    @mcu_connections.command(name="collection")
    @app_commands.describe(collection="Collection to search for.")
    async def mc_collection(self, interaction: discord.Interaction, collection: str):
        """Shared cast between MCU and a film collection."""
        if not await self.loaded(interaction):
            return

        response = await self.bot.loop.run_in_executor(
            None, partial(self.search.collection, query=collection)
        )
        if not response["results"]:
            return await interaction.followup.send(
                f"`{collection}` returned no results."
            )

        result = response["results"][0]

        try:
            project = await self.bot.loop.run_in_executor(
                None, tmdb.Collections, result["id"]
            )
        except HTTPError:
            return await interaction.followup.send(f"API Request Failed.")

        await self.bot.loop.run_in_executor(None, project.info)
        name = project.name

        creds = {"cast": [], "crew": []}
        for p in project.parts:
            if await self.within(interaction, name, p["id"]):
                return

            c = await self.bot.loop.run_in_executor(
                None,
                (
                    await self.bot.loop.run_in_executor(None, tmdb.Movies, p["id"])
                ).credits,
            )
            creds["cast"] += c["cast"]
            creds["crew"] += c["crew"]
        creds["cast"].sort(key=lambda x: x["order"])

        try:
            await interaction.followup.send(embeds=self.connections(name, creds))
        except HTTPException:
            await interaction.followup.send("... the list is too long")


async def setup(bot):
    await bot.add_cog(MoviesCog(bot))
