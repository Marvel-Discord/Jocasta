import asyncio
import asyncpg
import datetime as _dt
import enum
import math
import random
import re
import traceback

from contextlib import asynccontextmanager
from discord import *
from discord.app_commands import *
from discord.app_commands.tree import _log

from cogs.time import TimeCog
from config import *
from funcs.buttonpaginator import *
from funcs.polls_api import PollsAPIError

"""
x Create polls
x Delete polls
x View polls
x Search polls
x Edit polls
x Schedule polls
x Start polls
x End polls

x SQL DB
x Slashies
x Schedule timer
x Startup timer
  x Check on threads
x Force sync update

x Vote on poll
  x update message function
  x update votes values in SQL function
x Add reaction adds to thread

x add description to poll qs
x add server to poll qs
x tags stored in SQL
x poll info per server
  x server id
  x manager role
  x tags
  x external command channel access
  x colour
x Search polls only by server
- Search all polls
x Server/channel/message IDs for crossposts
x Poll access perms by server

x fix tags for search

x table for votes
x question values
  x show question
  x show options
  x show votes

x show user history
  x show unvoted polls

x tags
  x create
  x edit
  x crosspost

x end message repeat
x end message ping
x end message gives role

x update message gets in queue
  x if flag doesn't exist, trigger function that sets flag to false, updates message, and waits x secs
  x if flag already exists, set to true (if not already)
  x function loops ONLY IF flag is true
x recover buttons on start

- make fetching crossposts more efficient by indexing

x TOTAL VOTES

x info embed when voting
x better more informative info embed
x ditto for schedule embed
x format duration in info embed
x new embed for pretty

x fix search with better regex or smth

x set up better config

x me command single polls
- delete message doesn't break bot
x move database to testing
x check perms for commands

x on-startup views check for archived polls
- countdown command

- tag schedule queue

- admin: see who's voted


- make a poll object



to test:
x auto schedule start
x auto schedule end
x schedule on schedule command
x schedule on start command
x schedule on end command
x questions with same time diff tags processed separately
x editing embed with hiding things

"""


# id (int), num (int), time (datetime), message_id (int), question (str), thread_question (str), choices (str[]), votes (int[]), image (str), published (bool), duration (datetime), guild_id (int), description (str), tag (int), show_question (bool), show_options (bool), show_voting (bool), active (bool), crosspost_message_ids (int[])


def poll_manager_only():
    async def actual_check(interaction: Interaction):
        return await interaction.client.hasmanagerperms(interaction)

    return app_commands.check(actual_check)


def owner_only():
    async def actual_check(interaction: Interaction):
        return await interaction.client.is_owner(interaction.user)

    return app_commands.check(actual_check)


def valid_guild_only():
    async def actual_check(interaction: Interaction):
        bot = interaction.client
        return await bot.validguild(interaction) or await bot.ismanagechannel(
            interaction.channel_id
        )

    return app_commands.check(actual_check)


class PollsCog(commands.Cog, name="Polls"):
    """Polls commands"""

    def __init__(self, bot):
        self.bot = bot

        self.bot.tree.on_error = self.on_app_command_error

        self.bot.tasks["poll_schedules"] = {
            "starts": {},
            "ends": {},
        }

        self.bot.updatemsg_lock = asyncio.Lock()
        self.bot.updatemsg_flags = {}

        self.sort = {
            self.Sort.poll_id: "Poll ID",
            self.Sort.newest: "Newest",
            self.Sort.oldest: "Oldest",
            self.Sort.most_votes: "Most votes",
            self.Sort.least_votes: "Least votes",
        }

        self.bot.hasmanagerperms = self.hasmanagerperms
        self.bot.ismanagechannel = self.ismanagechannel
        self.bot.validguild = self.validguild

        self.maxqlength = 200

        self.bot.loop.create_task(self.on_startup_scheduler())

        # Add listener setup
        self.listener_connection = None
        self.listening = False

        # Start the listener
        self.bot.loop.create_task(self.setup_poll_listener())

    findchoice = lambda self, choices, x: [i for i in choices if i.value == x][0]

    choices = {}

    class Sort(enum.Enum):
        poll_id = "Poll ID"
        newest = "Newest"
        oldest = "Oldest"
        most_votes = "Most votes"
        least_votes = "Least votes"

    choices["sort"] = [
        Choice(name=v.value, value=e) for e, v in dict(Sort.__members__).items()
    ]

    datetosql = lambda self, x: x.strftime("%Y-%m-%d %H:%M:%S")
    strf = lambda self, x: x.strftime("%a, %b %d, %Y ~ %I:%M:%S %p %Z%z").replace(
        " 0", " "
    )
    # Sun, Mar 6, 2022 ~ 3:30 PM UTC
    s = lambda self, x: "" if x == 1 else "s"

    def strfdelta(self, tdelta):
        d = {}
        d["week"], d["day"] = divmod(tdelta.days, 7)
        d["hour"], rem = divmod(tdelta.seconds, 3600)
        d["minute"], d["second"] = divmod(rem, 60)
        return d

    def strfduration(self, tdt):
        txt = []
        for k, v in self.strfdelta(tdt).items():
            if v:
                txt.append(f"{v} {k}{self.s(v)}")
        return ", ".join(txt)

    choiceformats = [
        "<:A_p:1013463917843976212>",
        "<:B_p:1013463919794335914>",
        "<:C_p:1013463921614651463>",
        "<:D_p:1013463923531460628>",
        "<:E_p:1013463925049802934>",
        "<:F_p:1013463927276974170>",
        "<:G_p:1013463930204594206>",
        "<:H_p:1013463932171718666>",
    ]
    choiceformat = lambda self, x: self.choiceformats[x]

    lineformats = [
        "<:lf:1013463941172703344>",
        "<:le:1013463936135331860>",
        "<:lfc:1013463943202738276>",
        "<:lec:1013463939327205467>",
        "<:ld:1013463933966884865>",
    ]

    def lineformat(self, x):
        if not x:
            return self.lineformats[3]

        txt = [0] * (x - 1) + [1]
        txt[0] = txt[0] + 2

        return "".join([self.lineformats[i] for i in txt])

    def truncate(self, x, y=None, *, length=100):
        y = " " + y if y else ""
        length -= len(y)
        if len(x) > length:
            words = x.split(" ")
            i = 1
            while len(" ".join(words[: i + 1])) <= length - 3 and i < len(words):
                i += 1
            return " ".join(words[:i]) + "..." + y
        return x + y

    async def search_polls_by_id(self, poll_id, show_unpublished=False):
        polls = await self.fetch_all_polls(show_unpublished=show_unpublished)
        if not show_unpublished:
            polls = [poll for poll in polls if poll["published"]]
        prefix = str(poll_id)
        return [poll for poll in polls if str(poll["id"]).startswith(prefix)]

    async def search_polls_by_keyword(self, keyword, show_unpublished=False):
        # async with self.acquire_bot_conn() as conn:
        #     if show_unpublished:
        #         return await conn.fetch("SELECT * FROM polls WHERE question ~* $1", keyword)
        #     else:
        #         return await conn.fetch("SELECT * FROM polls WHERE question ~* $1 AND published = true", keyword)
        results = await self.fetch_all_polls(show_unpublished=show_unpublished)

        return self.keywordsearch(keyword, results)

    def keywordsearch(self, keyword, polls):
        alnum = lambda x: re.sub(r"[\W_]+", "", x.lower())
        lowered = alnum(keyword)
        return [
            i
            for i in polls
            if (
                any(
                    lowered in alnum(i[j])
                    for j in ["question", "thread_question", "description"]
                    if isinstance(i[j], str)
                )
                or any(lowered in alnum(j) for j in i["choices"])
            )
        ]

    def search_matches(self, poll, tag, published, active, notag):
        if tag == int(notag) and poll.tag is not None:
            return False
        if published is not None and poll.published != published:
            return False
        if active is not None and poll.active != active:
            return False
        return True

    def polls_guild_id(self) -> int:
        if self.guild_ids:
            return self.guild_ids[0]
        return self.bot.guilds[0].id

    def poll_dict(self, poll, tag: dict | None = None, guild: dict | None = None) -> dict:
        d = poll.model_dump()
        d["duration"] = poll.end_time - poll.start_time if poll.start_time and poll.end_time else None
        if tag:
            d.update(tag)
        if guild:
            d.update(guild)
        return d

    async def fetch_all_polls(self, show_unpublished=False):
        guild_id = self.polls_guild_id()
        guild = await self.fetch_guild_info(guild_id)
        tags = {t["tag"]: t for t in await self.fetch_all_tags()}
        polls = await self.bot.polls_api.sync_all_polls(guildId=guild_id)
        out = [self.poll_dict(poll, tags.get(poll.tag), guild) for poll in polls]
        if not show_unpublished:
            out = [poll for poll in out if poll["published"]]
        return out

    async def fetch_poll(self, poll_id: int):
        try:
            poll = await self.bot.polls_api.get_poll(poll_id)
        except PollsAPIError as e:
            if e.status == 404:
                return None
            raise
        tag = await self.fetch_tag(poll.tag)
        guild = await self.fetch_guild_info(poll.guild_id)
        return self.poll_dict(poll, tag, guild)

    async def fetchpollmsg(self, poll):
        return await self.bot.get_channel(
            poll["channel_id"] if not poll["fallback"] else poll["fallback_channel_id"]
        ).fetch_message(poll["message_id"])

    async def fetch_guild_info(self, guild_id: int):
        try:
            guild = await self.bot.polls_api.get_guild(guild_id)
        except PollsAPIError as e:
            if e.status == 404:
                return None
            raise
        return guild.model_dump()

    async def fetch_guild_info_by_manage_channel(self, channel_id: int):
        guild = await self.fetch_guild_info(self.polls_guild_id())
        if guild and channel_id in guild["manage_channel_id"]:
            return guild
        return None

    async def fetch_tag(self, tag_id: int):
        if not tag_id:
            return None
        try:
            tag = await self.bot.polls_api.get_tag(tag_id)
        except PollsAPIError as e:
            if e.status == 404:
                return None
            raise
        return tag.model_dump()

    async def fetch_tags_by_guild_id(self, guild_id: int):
        tags = await self.fetch_all_tags()
        return [tag for tag in tags if tag["guild_id"] == guild_id]

    async def fetch_all_tags(self, **params):
        tags = await self.bot.polls_api.get_tags(**params)
        return [tag.model_dump() for tag in tags]

    async def tagname(self, tagid: int):
        return (await self.fetch_tag(tagid))["name"]

    async def tagcolour(self, tagid: int):
        return (await self.fetch_tag(tagid))["colour"]

    async def fetchcolourbyid(self, guildid: int, tagid: int):
        guild = await self.fetch_guild_info(guildid)
        tag = await self.fetch_tag(tagid)

        return self.fetchcolour(guild, tag)

    def fetchcolour(self, guild, tag):
        if tag and tag["colour"]:
            return tag["colour"]
        else:
            return guild["default_colour"]

    def fetchchannelid(self, guild, tag):
        if tag and tag["channel_id"]:
            return tag["channel_id"]
        else:
            return guild["default_channel_id"]

    async def fetchguildid(self, interaction: discord.Interaction):
        return (
            (await self.fetch_guild_info_by_manage_channel(interaction.channel_id))[
                "guild_id"
            ]
            if await self.ismanagechannel(interaction.channel_id)
            else interaction.guild_id
        )

    async def ismanagechannel(self, channelid: int):
        return await self.fetch_guild_info_by_manage_channel(channelid) is not None

    async def validguild(self, interaction: discord.Interaction):
        return await self.fetch_guild_info(interaction.guild_id) is not None

    async def hasmanagerperms(self, interaction: discord.Interaction):
        return await self.has_manager_perms_by_user_and_ids(
            interaction.user, interaction.guild_id, interaction.channel_id
        )

    async def has_manager_perms_by_user_and_ids(self, user, guild_id, channel_id=None):
        guild = await self.fetch_guild_info(guild_id)
        if not guild:
            return []
        guilds = []
        if channel_id and channel_id in guild["manage_channel_id"]:
            guilds.append(guild["guild_id"])
        if any(r.id in guild["manager_role_id"] for r in user.roles):
            if guild["guild_id"] not in guilds:
                guilds.append(guild["guild_id"])
        return guilds

    async def canview(self, poll, guild_id):
        if guild_id == poll["guild_id"]:
            return True
        else:
            tag = await self.fetch_tag(poll["tag"])
            return tag and guild_id in tag["crosspost_servers"]

    async def validtag(self, tag, key=lambda x: True):
        if tag.isdigit():
            tagobj = await self.fetch_tag(int(tag))
            if tagobj and key(tagobj):
                return tagobj
            else:
                return None
        else:
            return None

    class Confirm(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.value = None
            self.interaction = None

        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
        async def confirm(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            self.value = True
            self.interaction = interaction
            await self.interaction.response.defer()
            self.stop()

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
        async def cancel(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            self.value = False
            self.interaction = interaction
            await self.interaction.response.defer()
            self.stop()

    @commands.command()
    @commands.is_owner()
    async def pools(self, ctx):
        async with self.acquire_bot_conn() as conn:
            # await conn.execute("INSERT INTO polls VALUES (1, null, null, null, 'test q', 'thread q', ARRAY ['a1', 'a2', 'a3'], 'comic', ARRAY [0, 0, 0])")
            # await conn.execute("INSERT INTO polls (id) VALUES (2)")
            #
            # await conn.execute("DELETE FROM polls WHERE id=1")
            #
            # a = await conn.fetchrow("SELECT id FROM polls")
            # print(type(a))
            # print(a['id'])
            #
            # print(bool(await conn.fetchrow("SELECT id FROM polls WHERE id = $1", 88375)))
            #
            # await conn.execute(f"UPDATE polls SET time = $1, duration = $2 WHERE id = $3", discord.utils.utcnow(), _dt.timedelta(seconds=100), 63830)
            #
            # a = await conn.fetchrow("SELECT * FROM polls WHERE id = $1", 63830)
            # print(type(a['time']), a['time'])
            # print(type(a['duration']), a['duration'])
            #
            # await self.schedule_starts()
            #
            # await ctx.send(embed = await self.pollinfoembed(await self.fetch_poll(60320)), view = await self.pollbuttons(60320))
            #
            # await self.vote({'id': 88071}, ctx.author, 1)
            #
            # url = "https://i.imgur.com/4Iz84pD.png"
            # async with aiohttp.ClientSession() as s:
            #     async with s.get(url) as r:
            #         f = discord.File(io.BytesIO(await r.read()), filename = "image.png", description = "test")
            #
            # e = discord.Embed(colour = 0x2f3136)
            # e.set_image(url="attachment://image.png")
            # # await ctx.send(file=f, embed=e)
            # await ctx.send(file=f)
            #
            # votes = await conn.fetch("SELECT * FROM pollsvotes")
            #
            # for user in votes:
            #     user_id = user['user_id']
            #     for p, v in user.items():
            #         if p == 'user_id':
            #             continue
            #         if v is not None:
            #             await conn.execute(
            #                 "INSERT INTO pollsvotesnew (id, user_id, poll_id, choice) VALUES ($1, $2, $3, $4)",
            #                 user_id + int(p), user_id, int(p), v)
            #             print(user_id, p, v)
            #
            # print((await conn.fetch("SELECT * FROM pollsvotesnew"))[0])

            polls = await conn.fetch(
                "SELECT * FROM (polls LEFT JOIN pollsinfo ON polls.guild_id = pollsinfo.guild_id) LEFT JOIN pollstags ON polls.tag = pollstags.tag "
                "WHERE time < TO_TIMESTAMP(1684627200)"
                "ORDER BY time ASC"
            )

            channel = self.bot.get_channel(1214133803107491840)

            for poll in polls:
                msg_content = await self.formatpollmessage(poll)
                msg = await channel.send(**msg_content)

                await conn.execute(
                    "UPDATE polls SET message_id = $1, fallback = true WHERE id = $2",
                    msg.id,
                    poll["id"],
                )

            print("done")

        pass

    async def pollinfoembed(self, poll, *, guild=None, tag=None):
        if not guild:
            guild = await self.fetch_guild_info(poll["guild_id"])
        if not tag:
            tag = await self.fetch_tag(poll["tag"])

        if not poll["num"]:
            embed = discord.Embed(title=poll["question"])
        else:
            embed = discord.Embed(title=f"#{poll['num']}: {poll['question']}")

        embed.set_author(
            name="🔗 View in browser",
            url=f"https://polls.marvelcord.com/?type=id&search={poll['id']}",
        )

        embed.description = poll["description"]

        embed.colour = self.fetchcolour(guild, tag)

        if not poll["votes"]:
            embed.add_field(
                name="Choices",
                value="\n".join([f"- {c}" for c in poll["choices"]]),
                inline=False,
            )
        else:
            embed.add_field(
                name="Choices",
                value="\n".join(
                    [f"- ({v}) {c}" for v, c in zip(poll["votes"], poll["choices"])]
                )
                + f"\nTotal votes: **{sum(poll['votes'])}**",
                inline=False,
            )

        embed.add_field(name="Published?", value=poll["published"])
        embed.add_field(name="Active?", value=poll["active"])

        if poll["thread_question"]:
            if not self.defaultthreadmsg(poll["thread_question"])[0]:
                embed.add_field(name="Thread Question", value=poll["thread_question"])
            else:
                embed.add_field(name="Thread Question", value="`Default`")
        if poll["tag"]:
            embed.add_field(name="Tag", value=f"`{tag['name']}`")

        if poll["time"]:
            embed.add_field(
                name="Publish Date",
                value=f"<t:{int(poll['time'].timestamp())}:F> (`{int(poll['time'].timestamp())}`)",
            )
        if poll["duration"]:
            embed.add_field(name="Duration", value=self.strfduration(poll["duration"]))

        if poll["message_id"]:
            try:
                # message = await self.bot.get_channel(self.fetchchannelid(guild, tag)).fetch_message(poll['message_id'])
                message = await self.fetchpollmsg(poll)
                embed.add_field(
                    name="Poll Message",
                    value=f"[{poll['question']}]({message.jump_url})",
                )
            except NotFound:
                embed.add_field(
                    name="Poll Message",
                    value=f"Can't locate message {poll['message_id']}",
                )

        display = [
            [poll["show_question"], "Question"],
            [poll["show_options"], "Options"],
            [poll["show_voting"], "Current Votes"],
        ]
        displaysort = {"Showing": [], "Not showing": []}
        [
            (
                displaysort["Showing"].append(i[1])
                if i[0]
                else displaysort["Not showing"].append(i[1])
            )
            for i in display
        ]
        embed.add_field(
            name="Display",
            value="\n".join(
                [f"{k}: {', '.join(v)}" for k, v in displaysort.items() if v]
            ),
        )

        if poll["image"]:
            embed.set_image(url=poll["image"])

        embed.set_footer(text=f"ID: {poll['id']} | {guild['guild_id']}")

        return embed

    async def pollquestionembed(
        self, poll, *, guild=None, tag=None, interaction=None, showextra=False
    ):
        if not guild:
            guild = await self.fetch_guild_info(poll["guild_id"])
        if not tag:
            tag = await self.fetch_tag(poll["tag"])

        if showextra and interaction is None:
            showextra = False

        embed = discord.Embed()

        embed.set_author(
            name="🔗 View in browser",
            url=f"https://polls.marvelcord.com/?type=id&search={poll['id']}",
        )

        if poll["show_question"]:
            embed.title = poll["question"]
            embed.description = poll["description"]

        embed.colour = self.fetchcolour(guild, tag)

        txt = []
        if poll["published"]:
            max_length = 10
            max_vote = max(poll["votes"])
            total_votes = sum(poll["votes"])
            for c, v, n in zip(
                poll["choices"], poll["votes"], range(len(poll["choices"]))
            ):
                if poll["show_voting"]:
                    x = (v * max_length) // max_vote if max_vote else 0
                    p = v / total_votes if total_votes else 0
                    if poll["show_options"]:
                        embed.add_field(
                            name=f"{self.lineformats[4]} {c}",
                            value=f"{self.choiceformat(n)}{self.lineformat(x)} **{v}** vote{self.s(v)} ({round(p * 100)}%)",
                            inline=False,
                        )
                    else:
                        txt.append(
                            f"{self.choiceformat(n)}{self.lineformat(x)} **{v}** vote{self.s(v)} ({round(p * 100)}%)"
                        )
                elif poll["show_options"]:
                    txt.append(f"{self.choiceformat(n)} {poll['choices'][n]}")
            txt.append(f"Total votes: **{sum(poll['votes'])}**")
        else:
            for c, n in zip(poll["choices"], range(len(poll["choices"]))):
                if poll["show_options"]:
                    txt.append(f"{self.choiceformat(n)} {poll['choices'][n]}")
        if txt:
            if not poll["show_voting"]:
                embed.add_field(name="Choices", value="\n".join(txt), inline=False)
            else:
                if not poll["show_options"]:

                    cap = 0
                    while len("\n".join(txt[: cap + 1])) <= 1024:
                        if cap == len(txt):
                            break
                        cap += 1

                    embed.add_field(
                        name="Choices", value="\n".join(txt[:cap]), inline=False
                    )
                    if txt[cap:]:
                        embed.add_field(
                            name="--", value="\n".join(txt[cap:]), inline=False
                        )
                else:
                    embed.add_field(name="Voting", value="\n".join(txt))

        name = None
        value = None
        if poll["duration"] and poll["published"] and not poll["persistent"]:
            end_time = poll["time"] + poll["duration"]
            if poll["active"]:
                name = "Poll ends"
            else:
                name = "Poll finished"
            value = "<t:{0}:R>\n".format(int(end_time.timestamp()))

        if name and value:
            embed.add_field(name=name, value=value)

        if showextra and poll["published"]:
            try:
                if interaction.guild_id == poll["guild_id"]:
                    if not tag:
                        msg = await interaction.guild.get_channel(
                            self.fetchchannelid(guild, tag)
                        ).fetch_message(poll["message_id"])
                    else:
                        msg = await interaction.guild.get_channel(
                            tag["channel_id"]
                        ).fetch_message(poll["message_id"])
                elif tag and interaction.guild_id in tag["crosspost_servers"]:
                    found = False
                    for cid in tag["crosspost_channels"]:
                        channel = interaction.guild.get_channel(cid)
                        if channel:
                            for mid in poll["crosspost_message_ids"]:
                                try:
                                    msg = await channel.fetch_message(mid)
                                except NotFound:
                                    continue
                                else:
                                    found = True
                                    break
                        if found:
                            break

                if msg:
                    if poll["active"]:
                        value += f"Vote [here](<{msg.jump_url}>)!"
                    else:
                        value += f"View poll [here](<{msg.jump_url}>)."
            except NotFound:
                pass

        if poll["thread_question"] and (not showextra or poll["active"]):
            threadq = self.defaultthreadmsg(poll["thread_question"])
            if not threadq[0]:
                embed.add_field(name="Discuss in the thread:", value=threadq[1])

        if poll["image"]:
            embed.set_image(url=poll["image"])

        if tag:
            if poll["num"]:
                embed.set_footer(
                    text=f"#{poll['num']} • {tag['name']} • [{poll['id']}]"
                )
            else:
                embed.set_footer(text=f"{tag['name']} • [{poll['id']}]")
        else:
            embed.set_footer(text=f"[{poll['id']}]")

        return embed

    async def pollfooterembed(self, poll, user, *, guild=None, tag=None):
        if not guild:
            guild = await self.fetch_guild_info(poll["guild_id"])
        if not tag:
            tag = await self.fetch_tag(poll["tag"])

        embed = discord.Embed()

        embed.set_author(
            name="🔗 View in browser",
            url=f"https://polls.marvelcord.com/?type=id&search={poll['id']}",
        )

        if poll["show_question"]:
            if not poll["num"]:
                embed.title = poll["question"]
            else:
                embed.title = f"#{poll['num']}: {poll['question']}"

        embed.colour = self.fetchcolour(guild, tag)

        if poll["show_voting"] or await self.has_manager_perms_by_user_and_ids(
            user, guild["guild_id"]
        ):
            txt = []
            max_length = 10
            max_vote = max(poll["votes"])
            total_votes = sum(poll["votes"])
            for c, v, n in zip(
                poll["choices"], poll["votes"], range(len(poll["choices"]))
            ):
                x = (v * max_length) // max_vote if max_vote else 0
                p = v / total_votes if total_votes else 0
                txt.append(
                    f"{self.choiceformat(n)}{self.lineformat(x)} **{v}** vote{self.s(v)} ({round(p * 100, 2)}%)"
                )

            ishidden = not poll["show_voting"]

            cap = 0
            while len("\n".join(txt[: cap + 1])) <= 1024:
                if cap == len(txt):
                    break
                cap += 1

            embed.add_field(
                name=f"Votes {'(not revealed publicly, keep it a secret!)' if ishidden else ''}",
                value="\n".join(txt[:cap]),
                inline=False,
            )
            if txt[cap:]:
                embed.add_field(name="--", value="\n".join(txt[cap:]), inline=False)

        else:
            embed.add_field(name="Votes", value="Votes are hidden!")

        txt = []
        vote = await self.get_user_vote(poll, user)
        if vote is not None:
            txt.append(f"You've voted: {self.choiceformat(vote)}")
            if poll["show_options"]:
                txt[-1] += f" *{poll['choices'][vote]}*"
        else:
            if poll["active"]:
                txt.append(f"You haven't voted yet!")
            else:
                txt.append(f"You didn't vote!")

        embed.add_field(name="Your vote", value="\n".join(txt))

        return embed

    def sortpolls(self, polls: list, sort: Sort = Sort.newest):
        # poll id, newest, oldest, most votes, least votes
        polls.sort(key=lambda x: x["id"])  # base poll id order

        if sort == self.Sort.poll_id:
            key = lambda x: x["id"]
        elif sort == self.Sort.newest:
            key = lambda x: x["time"].timestamp() * -1 if x["time"] else 1
        elif sort == self.Sort.oldest:
            key = lambda x: (
                x["time"].timestamp() if x["time"] else 99999999999999999999999999999999
            )
        elif sort == self.Sort.most_votes:
            key = lambda x: sum(x["votes"]) * -1 if x["votes"] else 1
        elif sort == self.Sort.least_votes:
            key = lambda x: (
                sum(x["votes"]) if x["votes"] else 99999999999999999999999999999999
            )
        else:
            key = None

        if key:
            polls.sort(key=key)

        return polls

    guild_ids = None if global_slashies else guild_ids

    pollsgroup = app_commands.Group(
        name="polls", description="Poll commands", guild_ids=guild_ids
    )

    pollsadmingroup = app_commands.Group(
        name="pollsadmin",
        description="Poll administrative commands",
        guild_ids=guild_ids,
    )

    async def autocomplete_tag(
        self,
        interaction: discord.Interaction,
        current: str,
        *,
        clear=None,
        clearname="Clear tag.",
        local=True,
    ):
        if clear is not None:
            emptychoice = app_commands.Choice(name=clearname, value=clear)
            if current == clear:
                return [emptychoice]
        if local:
            tags = await self.fetch_tags_by_guild_id(interaction.guild_id)
        else:
            tags = await self.fetch_all_tags()
        tags.sort(key=lambda x: x["name"])
        tag_choices = [
            app_commands.Choice(name=t["name"], value=str(t["tag"]))
            for t in tags
            if re.search(f"^{current.lower()}", t["name"], re.IGNORECASE)
        ][:25]
        if current == "" and clear is not None:
            tag_choices = tag_choices[:24]
            tag_choices.append(emptychoice)
        return tag_choices

    async def autocomplete_searchbypollid(
        self,
        interaction: discord.Interaction,
        current: int,
        *,
        published=None,
        active=None,
        returnresults=False,
        local=True,
        crosspost=False,
    ):
        if current.isdigit():
            current = int(current)
            if current <= 99999:
                results = await self.search_polls_by_id(
                    current, await self.hasmanagerperms(interaction)
                )
                results = self.sortpolls(results)
            else:
                results = []
        else:
            results = await self.search_polls_by_keyword(
                current, await self.hasmanagerperms(interaction)
            )
            lowered = current.lower()
            regex = [f"^\b{lowered}\b", f"\b{lowered}\b", f"^{lowered}", lowered, ""]
            results = self.sortpolls(results)
            results.sort(
                key=lambda x: [
                    bool(re.search(i, x["question"].lower())) for i in regex
                ].index(True)
            )

        if published is not None:
            results = [i for i in results if i["published"] == published]
        if active is not None:
            results = [i for i in results if i["active"] == active]

        if local:
            tags = await self.fetch_all_tags()
            findtag = lambda x: next(i for i in tags if i["id"] == x["tag"])

            guilds = await self.hasmanagerperms(interaction)
            if interaction.guild_id not in guilds:
                guilds.append(interaction.guild_id)
            newresults = []
            for i in results:
                if i["guild_id"] in guilds:
                    newresults.append(i)
                elif crosspost:
                    try:
                        crosspostmatch = [
                            g in findtag(i)["crosspost_servers"] for g in guilds
                        ]
                        if any(crosspostmatch):
                            newresults.append(i)
                    except StopIteration:
                        continue
            results = newresults
        # results = [i for i in results if i['guild_id'] in guilds or (any(g in findtag(i)['crosspost_servers'] for g in guilds) and crosspost)]

        if returnresults:
            return results

        choices = [
            app_commands.Choice(
                name=self.truncate(f"[{i['id']}] {i['question']}"), value=i["id"]
            )
            for i in results[:25]
        ]
        return choices

    async def autocomplete_duration(
        self, interaction: discord.Interaction, current: float, *, clear=None
    ):
        choices = []

        strcurrent = (
            current
            if isinstance(current, str)
            else (str(current) if not math.isnan(current) else "")
        )
        try:
            current = float(current)

            if clear and (current == clear or math.isnan(current)):
                choices += [
                    app_commands.Choice(name=f"Clear duration value.", value=-1)
                ]

            if current < discord.utils.utcnow().timestamp():
                ranges = {
                    "seconds": "second",
                    "minutes": "minute",
                    "hours": "hour",
                    "days": "day",
                    "weeks": "week",
                }
                times = []
                for k, v in ranges.items():
                    try:
                        times.append([_dt.timedelta(**{k: current}), v])
                    except OverflowError:
                        continue

                for t in times:
                    secs = int(round(t[0].total_seconds(), 0))
                    if 15 <= secs <= 60480000:  # Between 15s and 100w
                        f = lambda x: int(x) if x.is_integer() else x
                        choices.append(
                            app_commands.Choice(
                                name=f"{f(current)} {t[1]}{self.s(f(current))}",
                                value=secs,
                            )
                        )
        except ValueError:
            pass

        if not isinstance(current, float) or current >= 1970 or math.isnan(current):
            timestamp = TimeCog.strtodatetime(TimeCog, strcurrent)
            choices += [
                app_commands.Choice(
                    name=f"End at: {self.strf(t)}", value=int(t.timestamp())
                )
                for t in timestamp
            ]

        return choices[:25]

    async def on_app_command_error(
        self, interaction: Interaction, error: AppCommandError
    ):
        if isinstance(error, app_commands.errors.CheckFailure):
            if await self.validguild(interaction):
                return await interaction.response.send_message(
                    f"You need to be a <@&{(await self.fetch_guild_info(interaction.guild_id))['manager_role_id'][0]}> to do that!",
                    ephemeral=True,
                )
            else:
                return await interaction.response.send_message(
                    f"This command is not available here!", ephemeral=True
                )

        await interaction.followup.send("Something broke!")
        _log.error(
            "Ignoring exception in command %r", interaction.command.name, exc_info=error
        )

    # PostgreSQL LISTEN/NOTIFY for poll updates #

    def listener_log(self, msg):
        if database_listener_logs:
            print(f"[Polls Listener] {msg}")

    async def setup_poll_listener(self):
        """Set up PostgreSQL LISTEN connection for poll updates"""
        await self.bot.wait_until_ready()

        while not hasattr(self.bot, "db") or not self.bot.db:
            await asyncio.sleep(0.1)

        try:
            # Create dedicated connection for listening
            self.listener_connection = await asyncpg.connect(**postgres_credentials)

            # Set platform and start listening
            await self.listener_connection.execute("SET application_name = 'bot'")
            await self.listener_connection.add_listener(
                "poll_updates", self.handle_poll_notification
            )

            self.listening = True
            self.listener_log("Started listening for poll updates")

            # Keep connection alive
            while self.listening:
                await asyncio.sleep(1)

        except Exception as e:
            self.listener_log(f"Error setting up listener: {e}")
            traceback.print_exc()
            # Retry after delay
            await asyncio.sleep(30)
            if self.listening:
                await self.setup_poll_listener()

    async def handle_poll_notification(self, connection, pid, channel, payload):
        """Handle incoming poll update notifications"""
        try:
            import json

            data = json.loads(payload)
            table = data.get("table")
            operation = data.get("operation")
            poll_id = data.get("id")
            platform = data.get("platform")

            # Ignore notifications from bot itself
            if platform == "bot":
                return

            self.listener_log(
                f"Received {operation} on {table} for ID {poll_id} from {platform}"
            )

            # Handle based on table and operation
            if table == "polls":
                await self.handle_poll_table_update(poll_id, operation)
            elif table == "pollsvotes":
                await self.handle_vote_table_update(poll_id, operation)

        except Exception as e:
            self.listener_log(f"Error handling notification: {e}")
            traceback.print_exc()

    async def handle_poll_table_update(self, poll_id, operation):
        """Handle updates to polls table"""
        try:
            if operation == "DELETE":
                self.listener_log(f"Poll {poll_id} was deleted")
                # Clean up any scheduled tasks
                for task_type in ["starts", "ends"]:
                    for key, task in list(
                        self.bot.tasks["poll_schedules"][task_type].items()
                    ):
                        if str(poll_id) in str(key):
                            task.cancel()
                            del self.bot.tasks["poll_schedules"][task_type][key]
                            self.listener_log(
                                f"Cancelled {task_type} task for poll {poll_id}"
                            )
                return

            # For INSERT/UPDATE, refresh poll data and update message
            poll = await self.fetch_poll(poll_id)
            if poll:
                if poll["published"]:
                    await self.updatepollmessage(poll)
                    self.listener_log(f"Updated message for poll {poll_id}")

                await self.update_poll_scheduling(poll)

        except Exception as e:
            self.listener_log(f"Error handling poll update for {poll_id}: {e}")
            traceback.print_exc()

    async def handle_vote_table_update(self, poll_id, operation):
        """Handle updates to pollsvotes table"""
        try:
            # For any vote change, update the poll message
            poll = await self.fetch_poll(poll_id)
            if poll and poll["published"]:
                await self.updatepollmessage(poll)
                self.listener_log(
                    f"Updated message for poll {poll_id} due to vote change"
                )

        except Exception as e:
            self.listener_log(f"Error handling vote update for {poll_id}: {e}")
            traceback.print_exc()

    async def update_poll_scheduling(self, poll):
        """Update scheduling for a poll that may have changed timing"""
        try:
            # Cancel existing schedules for this poll
            for task_type in ["starts", "ends"]:
                for key, task in list(
                    self.bot.tasks["poll_schedules"][task_type].items()
                ):
                    if str(poll["id"]) in str(key):
                        task.cancel()
                        del self.bot.tasks["poll_schedules"][task_type][key]
                        self.listener_log(
                            f"Cancelled {task_type} task for poll {poll['id']}"
                        )

            # Reschedule if needed
            if poll["time"] and not poll["published"]:
                await self.schedule_starts()
            if poll["duration"] and poll["active"]:
                await self.schedule_ends()

        except Exception as e:
            self.listener_log(f"Error updating scheduling for poll {poll['id']}: {e}")

    async def stop_listener(self):
        """Clean shutdown of the listener"""
        self.listening = False
        if hasattr(self, "listener_connection") and self.listener_connection:
            try:
                await self.listener_connection.remove_listener(
                    "poll_updates", self.handle_poll_notification
                )
                await self.listener_connection.close()
                self.listener_log(f"Stopped listening for poll updates")
            except Exception as e:
                self.listener_log(f"Error stopping listener: {e}")

    def cog_unload(self):
        """Clean up when the cog is unloaded"""
        if hasattr(self, "listener_connection") and self.listener_connection:
            asyncio.create_task(self.stop_listener())

    @asynccontextmanager
    async def acquire_bot_conn(self):
        conn = await self.bot.db.acquire()
        await conn.execute("SET application_name = 'bot'")
        try:
            yield conn
        finally:
            await self.bot.db.release(conn)

    # other stuff i haven't categorised yet #

    async def splitstartpolls(self, poll_ids: list, *, set_time=None, natural=False):
        if not isinstance(poll_ids, list):
            poll_ids = [poll_ids]

        polls = {}
        for poll_id in poll_ids:
            poll = await self.fetch_poll(poll_id)
            tag = await self.fetch_tag(poll["tag"])
            tid = None if not tag else tag["tag"]
            if tid in polls.keys():
                polls[tid].append(poll_id)
            else:
                polls[tid] = [poll_id]

        for t, p in polls.items():
            await self.startpolls(p, set_time=set_time, natural=natural)

    async def startpoll(self, poll_id, **kwargs):
        return await self.startpolls([poll_id], **kwargs)

    async def startpolls(self, poll_ids: list, *, set_time=None, natural=False):
        await self.bot.wait_until_ready()

        if not isinstance(poll_ids, list):
            poll_ids = [poll_ids]

        polls = []
        for poll_id in poll_ids:
            poll = await self.fetch_poll(poll_id)
            tag = await self.fetch_tag(poll["tag"])
            polls.append([poll, tag])

        tags = [tag["tag"] if tag else None for poll, tag in polls]
        if not tags.count(tags[0]) == len(tags):
            print("Can't bulk-start polls with different tags!")
            return None

        poll, tag = polls[0]
        guild = await self.fetch_guild_info(poll["guild_id"])
        channel_id = self.fetchchannelid(guild, tag)

        async with self.acquire_bot_conn() as conn:
            for poll, t in polls:
                num = None
                if tag:
                    if tag["current_num"]:
                        num = (await self.fetch_tag(poll["tag"]))["current_num"]
                        await conn.execute(
                            "UPDATE pollstags SET current_num = $2 WHERE tag = $1",
                            tag["tag"],
                            num + 1,
                        )

                votes = [0 for i in range(len(poll["choices"]))]

                await conn.execute(
                    "UPDATE polls SET published = $2, active = $3, votes = $4, num = $5 WHERE id = $1",
                    poll["id"],
                    True,
                    True,
                    votes,
                    num,
                )

                if set_time:
                    await conn.execute(
                        "UPDATE polls SET time = $2 WHERE id = $1", poll["id"], set_time
                    )

        msgs = [[await self.formatpollmessage(p), p] for p in [i[0] for i in polls]]
        final = []

        channel = self.bot.get_channel(channel_id)
        crossposts = (
            [self.bot.get_channel(i) for i in tag["crosspost_channels"]] if tag else []
        )

        async def send(txt, poll, channel, *, main=True):
            msg = await channel.send(**txt)

            if main:
                async with self.acquire_bot_conn() as conn:
                    await conn.execute(
                        "UPDATE polls SET message_id = $2 WHERE id = $1",
                        poll["id"],
                        msg.id,
                    )
            else:
                async with self.acquire_bot_conn() as conn:
                    await conn.execute(
                        "UPDATE polls SET crosspost_message_ids = crosspost_message_ids || $2 WHERE id = $1",
                        poll["id"],
                        [msg.id],
                    )

            if poll["thread_question"]:
                name = poll["question"]
                if poll["num"]:
                    name = f"{poll['num']} - {name}"
                try:
                    thread = await msg.create_thread(name=name)
                    threadmsg = self.defaultthreadmsg(poll["thread_question"])
                    if not threadmsg[0]:
                        threadq = await thread.send(threadmsg[1])
                        await threadq.pin()
                except commands.Forbidden:
                    pass

            return msg

        async with self.acquire_bot_conn() as conn:
            await conn.execute(
                "UPDATE polls SET crosspost_message_ids = $2 WHERE id = $1",
                poll["id"],
                [],
            )
        for txt, poll in msgs:
            final.append([poll, await send(txt, poll, channel)])
            for ch in crossposts:
                final.append([poll, await send(txt, poll, ch, main=False)])

        for poll, t in polls:
            if poll["time"]:  # needs to be old time
                await self.schedule_starts(
                    timestamps=[poll["time"].timestamp()],
                    natural=natural,
                    tag=poll["tag"],
                )
            if poll["duration"]:
                await self.schedule_ends(poll_ids=[poll["id"]], natural=natural)

        if tag and tag["end_message"]:
            txt = {"content": None, "embed": None, "view": None}

            view = None
            if tag["end_message_role_ids"] and tag["end_message_self_assign"]:
                view = self.SelfAssignRoleView(tag["end_message_role_ids"])

            txt["embed"] = discord.Embed(
                description=tag["end_message"],
                colour=await self.fetchcolourbyid(guild["guild_id"], tag["tag"]),
            )

            def getroles(channel):
                roles = []
                for r in tag["end_message_role_ids"]:
                    role = channel.guild.get_role(r)
                    if role:
                        roles.append(role)
                return roles

            roles = getroles(channel)
            txt["content"] = " ".join([r.mention for r in roles])
            txt["view"] = view if roles else None
            endmsgs = [await channel.send(**txt)]

            for ch in crossposts:
                roles = getroles(ch)
                txt["content"] = " ".join([r.mention for r in roles])
                txt["view"] = view if roles else None
                endmsgs.append(await ch.send(**txt))

            endmsgtags = [tag]
            if tag["end_message_replace"]:
                async with self.acquire_bot_conn() as conn:
                    alltags = await conn.fetch(
                        "SELECT * FROM pollstags WHERE end_message_replace = $1", True
                    )
                channels = [tag["channel_id"]] + tag["crosspost_channels"]
                endmsgtags += [
                    i
                    for i in alltags
                    if (
                        i["channel_id"] in channels
                        or any(j in channels for j in i["crosspost_channels"])
                    )
                    and i["tag"] != tag["tag"]
                ]

            for t in endmsgtags:
                if t["end_message_latest_ids"]:
                    latest = t["end_message_latest_ids"]
                    change = False
                    for message_id in latest:
                        for ch in [channel] + crossposts:
                            try:
                                msg = await ch.fetch_message(message_id)
                            except NotFound:
                                continue
                            else:
                                await msg.delete()
                                change = True
                                latest.remove(message_id)
                                break
                    if change:
                        async with self.acquire_bot_conn() as conn:
                            await conn.execute(
                                "UPDATE pollstags SET end_message_latest_ids = $2 WHERE tag = $1",
                                t["tag"],
                                latest,
                            )

            async with self.acquire_bot_conn() as conn:
                await conn.execute(
                    "UPDATE pollstags SET end_message_latest_ids = $2 WHERE tag = $1",
                    tag["tag"],
                    [m.id for m in endmsgs],
                )

        for poll, t in polls:
            poll = await self.fetch_poll(poll["id"])
            await self.updatepollmessage(poll)

        return final

    async def endpoll(self, poll_id, *, set_time=False, lock_thread=True, natural=True):

        if set_time:
            current_time = discord.utils.utcnow()

        poll = await self.fetch_poll(poll_id)
        tag = await self.fetch_tag(poll["tag"])
        guild = await self.fetch_guild_info(poll["guild_id"])

        channel_id = guild["default_channel_id"]
        if tag:
            if tag["channel_id"]:
                channel_id = tag["channel_id"]

        async with self.acquire_bot_conn() as conn:
            await conn.execute(
                "UPDATE polls SET active = $2 WHERE id = $1", poll["id"], False
            )

            if set_time:
                duration = current_time - poll["time"]
                await conn.execute(
                    "UPDATE polls SET duration = $2 WHERE id = $1", poll["id"], duration
                )

        if poll["duration"]:
            await self.schedule_ends(poll_ids=[poll["id"]], natural=natural)

        channel = self.bot.get_channel(channel_id)
        crossposts = (
            [self.bot.get_channel(i) for i in tag["crosspost_channels"]] if tag else []
        )

        guilds = [
            self.bot.get_guild(g) for g in {i.guild.id for i in [channel] + crossposts}
        ]

        try:
            if poll["thread_question"]:
                for thread_id in [poll["message_id"]] + (
                    poll["crosspost_message_ids"]
                    if poll["crosspost_message_ids"]
                    else []
                ):
                    for g in guilds:
                        thread = g.get_channel_or_thread(thread_id)
                        if thread is None:
                            continue
                        else:
                            await thread.edit(archived=True, locked=lock_thread)
                            break
        except Exception as e:
            traceback.print_exc()

        poll = await self.fetch_poll(poll["id"])
        await self.updatepollmessage(poll)

    async def scheduler(self, polls, start: bool):
        if not isinstance(polls, list):
            polls = [polls]

        if start:
            time = polls[0]["time"]
        else:
            time = polls[0]["time"] + polls[0]["duration"]

        # Saving on memory
        polls = [i["id"] for i in polls]

        sleepduration = time - discord.utils.utcnow()
        if sleepduration.total_seconds() > 0:
            print(
                f"[Polls Scheduler] ({', '.join(str(i) for i in polls)}) Started schedule \"{'start' if start else 'end'}\" to end in {sleepduration} ({time})"
            )
            await asyncio.sleep(sleepduration.total_seconds())
        else:
            print(
                f"[Polls Scheduler] ({', '.join(str(i) for i in polls)}) {'Started' if start else 'Ended'} poll immediately from overdue timer ({time})"
            )

        if start:
            await self.splitstartpolls(polls, natural=True)
        else:
            for p in polls:
                await self.endpoll(p, natural=True)

        print(
            f"[Polls Scheduler] ({', '.join(str(i) for i in polls)}) Successfully {'started' if start else 'ended'} poll"
        )

    async def schedule_starts(self, *, tag=0, timestamps=[], natural=False):
        async with self.acquire_bot_conn() as conn:
            polls = await conn.fetch(
                "SELECT * FROM polls WHERE time IS NOT NULL AND published = $1", False
            )

        for k, v in self.bot.tasks["poll_schedules"]["starts"].items():
            if (
                (not timestamps or k[1] in timestamps)
                and (tag == 0 or tag == k[0])
                and not natural
            ):
                print(
                    f'[Polls Scheduler] Cancelled "start" scheduler at {k[1]} ({_dt.datetime.fromtimestamp(k[1], _dt.timezone.utc)})'
                )
                v.cancel()

        groups = {}

        for p in polls:
            if (p["tag"], p["time"]) not in groups.keys():
                groups[(p["tag"], p["time"])] = [p]
            else:
                groups[(p["tag"], p["time"])].append(p)

        for k, v in groups.items():
            if k:
                if not timestamps or k[1].timestamp() in timestamps:
                    self.bot.tasks["poll_schedules"]["starts"][
                        (k[0], k[1].timestamp())
                    ] = self.bot.loop.create_task(self.scheduler(v, True))

    async def schedule_ends(self, *, poll_ids: list = [], natural=False):
        async with self.acquire_bot_conn() as conn:
            polls = await conn.fetch(
                "SELECT * FROM polls WHERE duration IS NOT NULL AND active = $1", True
            )

        for k, v in self.bot.tasks["poll_schedules"]["ends"].items():
            if (not poll_ids or k in poll_ids) and not natural:
                print(f'[Polls Scheduler] Cancelled "end" scheduler for ({k})')
                v.cancel()

        for p in polls:
            if p["duration"]:
                if not poll_ids or p["id"] in poll_ids:
                    self.bot.tasks["poll_schedules"]["ends"][p["id"]] = (
                        self.bot.loop.create_task(self.scheduler(p, False))
                    )

    async def on_startup_scheduler(self):
        while not self.bot.postgresql_loaded:
            await asyncio.sleep(0.1)
        self.bot.loop.create_task(self.schedule_starts())
        self.bot.loop.create_task(self.schedule_ends())
        self.bot.loop.create_task(self.on_startup_buttons())
        self.bot.loop.create_task(self.on_startup_self_assign())

    async def formatpollmessage(self, poll):
        content = None
        embed = await self.pollquestionembed(poll)
        view = await self.poll_buttons_id(
            poll["id"],
            active=(poll["active"] or poll["persistent"]) and poll["published"],
        )

        return {
            "content": content,
            "embed": embed,
            "view": view,
        }

    async def updatepollmessage(self, poll):
        async with self.bot.updatemsg_lock:
            if poll["id"] not in self.bot.updatemsg_flags.keys():
                self.bot.updatemsg_flags[poll["id"]] = True
                self.bot.loop.create_task(self.loop_updatepollmessage(poll))
            else:
                self.bot.updatemsg_flags[poll["id"]] = True

    async def loop_updatepollmessage(self, poll):
        while self.bot.updatemsg_flags[poll["id"]] == True:
            self.bot.updatemsg_flags[poll["id"]] = False

            try:
                await self.do_updatepollmessage(poll)
            except Exception:
                traceback.print_exc()

            wait = 2
            await asyncio.sleep(wait)
        self.bot.updatemsg_flags.pop(poll["id"])

    async def do_updatepollmessage(self, poll, force=False):
        tag = await self.fetch_tag(poll["tag"])

        crossposts = (
            [self.bot.get_channel(i) for i in tag["crosspost_channels"]] if tag else []
        )

        await self.updatevotes(poll)
        poll = await self.fetch_poll(poll["id"])

        if not poll["message_id"]:
            return

        txt = await self.formatpollmessage(poll)

        msg = await self.fetchpollmsg(poll)

        if (
            not force
            and txt["content"] == msg.content
            and msg.embeds
            and msg.embeds[0] == txt["embed"]
        ):
            print(
                force,
                txt["content"] == msg.content,
                bool(msg.embeds),
                msg.embeds[0] == txt["embed"],
            )
            return

        if msg.author.id == self.bot.user.id:
            await msg.edit(**txt)

        if poll["crosspost_message_ids"]:
            for mid in poll["crosspost_message_ids"]:
                for ch in crossposts:
                    try:
                        msg = await ch.fetch_message(mid)
                    except NotFound:
                        continue
                    else:
                        if msg.author.id == self.bot.user.id:
                            await msg.edit(**txt)

    async def updatevotes(self, poll):
        async with self.acquire_bot_conn() as conn:
            votes = await conn.fetch(
                "SELECT (choice) from pollsvotes WHERE poll_id = $1", poll["id"]
            )
            votes = [i["choice"] for i in votes]
            total = [votes.count(i) for i in range(len(poll["choices"]))]
            if total != poll["votes"]:
                await conn.execute(
                    "UPDATE polls SET votes = $2 WHERE id = $1", poll["id"], total
                )
        return total

    def defaultthreadmsg(self, msg, vote=None):
        default = False
        if str(msg).lower().strip() in ["def", "default"]:
            default = True
            if vote is not None:
                msg = f"Why did you choose *{vote}*?"
            else:
                msg = f"Why?"
        return [default, msg]

    class PollView(discord.ui.View):
        def __init__(self, client, poll, *, active=True):
            super().__init__(timeout=None)

            self.active = active

            if active:
                if len(poll["choices"]) <= 4:
                    for c, n in zip(poll["choices"], range(len(poll["choices"]))):
                        self.add_item(
                            self.ChoiceButton(
                                client,
                                poll,
                                self.vote,
                                emoji=client.choiceformat(n),
                                custom_id=f"{poll['id']}{n}",
                                row=(n) // 4,
                                disabled=not active,
                            )
                        )
                else:
                    self.add_item(
                        self.ChoiceOptions(
                            client,
                            poll,
                            self.vote,
                            custom_id=f"{poll['id']}^",
                            row=0,
                            disabled=not active,
                        )
                    )

                self.add_item(
                    self.ClearVoteButton(
                        client,
                        poll,
                        self.vote,
                        label="Clear Vote",
                        style=discord.ButtonStyle.red,
                        custom_id="-1",
                        row=2,
                        disabled=not active,
                    )
                )

            self.add_item(
                self.InfoButton(
                    client,
                    poll,
                    emoji="<:info:1014581512001294366>",
                    style=discord.ButtonStyle.green,
                    custom_id=str(poll["id"]),
                    row=2,
                )
            )

        async def vote(self, client, poll, interaction, value):
            await interaction.response.defer()

            poll = dict(await client.fetch_poll(poll["id"]))

            if self.active:
                try:
                    await client.cast_vote(poll, interaction.user, value)
                except PollsAPIError:
                    await interaction.followup.send(
                        "Something went wrong, please try again", ephemeral=True
                    )
                    return

                qid = (
                    f"*{poll['question']}* ({poll['id']})"
                    if poll["show_question"]
                    else f"`{poll['id']}`"
                )

                if value != -1:
                    if poll["show_options"]:
                        await interaction.followup.send(
                            f"On the poll {qid}, you voted:\n{client.choiceformat(value)}: {poll['choices'][value]}",
                            ephemeral=True,
                        )
                    else:
                        await interaction.followup.send(
                            f"On the poll {qid}, you voted:\n{client.choiceformat(value)}",
                            ephemeral=True,
                        )
                else:
                    await interaction.followup.send(
                        f"**Cleared** your vote on the poll {qid}", ephemeral=True
                    )

                await client.add_to_thread(interaction, poll, value)

            else:
                await interaction.followup.send(f"This poll has ended!", ephemeral=True)

        class ChoiceButton(discord.ui.Button):
            def __init__(self, client, poll, vote, **kwargs):
                super().__init__(**kwargs)
                self.client = client
                self.poll = poll
                self.vote = vote
                self.value = int(self.custom_id) % 10

            async def callback(self, interaction: discord.Interaction):
                await self.vote(self.client, self.poll, interaction, self.value)

        class ChoiceOptions(discord.ui.Select):
            def __init__(
                self, client, poll, vote, *, placeholder="Click here to vote", **kwargs
            ):
                self.client = client
                self.poll = poll
                self.vote = vote

                options = []

                for c, n in zip(poll["choices"], range(len(poll["choices"]))):
                    label = c if poll["show_options"] else "Vote!"
                    options.append(
                        discord.SelectOption(
                            emoji=client.choiceformat(n), value=str(n), label=label
                        )
                    )

                super().__init__(
                    placeholder=placeholder,
                    min_values=1,
                    max_values=1,
                    options=options,
                    **kwargs,
                )

            async def callback(self, interaction: discord.Interaction):
                await self.vote(
                    self.client, self.poll, interaction, int(self.values[0])
                )

        class ClearVoteButton(discord.ui.Button):
            def __init__(self, client, poll, vote, **kwargs):
                super().__init__(**kwargs)
                self.client = client
                self.poll = poll
                self.vote = vote

            async def callback(self, interaction: discord.Interaction):
                await self.vote(
                    self.client, self.poll, interaction, int(self.custom_id)
                )

        class InfoButton(discord.ui.Button):
            def __init__(self, client, poll, **kwargs):
                super().__init__(**kwargs)
                self.client = client
                self.poll = poll

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer()

                await interaction.followup.send(
                    embed=await self.client.pollfooterembed(
                        self.poll, interaction.user
                    ),
                    ephemeral=True,
                )

    async def poll_buttons_id(self, poll_id, **kwargs):
        poll = await self.fetch_poll(poll_id)
        return await self.poll_buttons(poll, **kwargs)

    async def poll_buttons(self, poll, **kwargs):
        return self.PollView(self, poll, **kwargs)

    async def on_startup_buttons(self):
        polls = await self.fetch_all_polls()
        polls.sort(key=lambda x: discord.utils.utcnow() - x["time"])
        polls.sort(key=lambda x: not x["active"])

        for poll in polls:
            view = await self.poll_buttons(
                poll,
                active=(poll["active"] or poll["persistent"]) and poll["published"],
            )
            self.bot.add_view(view)

    async def cast_vote(self, poll: dict, user, choice: int):
        """Cast, update, or delete a vote via the API (choice -1 = delete)."""
        api_choice = None if choice == -1 else choice
        counts = await self.bot.polls_api.cast_vote(
            poll["id"], user.id, api_choice
        )

        poll["votes"] = counts.votes
        poll["total_votes"] = counts.total_votes

        await self.updatepollmessage(poll)

        return choice

    async def get_user_vote(self, poll: dict, user):
        """Return the user's current vote for a poll, or None."""
        votes = await self.bot.polls_api.get_user_votes(user.id)
        for vote in votes:
            if vote.poll_id == poll["id"]:
                return vote.choice
        return None

    async def add_to_thread(self, interaction, poll=None, choice=None, show_vote=False):
        thread = interaction.message.guild.get_channel_or_thread(interaction.message.id)
        if thread and poll["thread_question"]:
            try:
                try:
                    await thread.fetch_member(interaction.user.id)
                except NotFound:
                    # await thread.add_user(interaction.user)
                    if choice is not None:
                        embed = discord.Embed()
                        threadmsg = self.defaultthreadmsg(
                            poll["thread_question"], poll["choices"][choice]
                        )
                        if not threadmsg[0]:
                            embed.description = f"Discuss: *{threadmsg[1]}*"
                            embed.set_footer(text="See pins for the above question!")
                        else:
                            embed.description = threadmsg[1]
                        await thread.send(
                            f"{interaction.user.mention}, thanks for voting!",
                            embed=embed,
                            delete_after=45,
                        )
            except Forbidden:
                pass
            finally:
                pass
            # if show_vote and poll and choice is not None:
            # 	embed = discord.Embed()
            # 	embed.description = f"{interaction.user.mention} voted for {self.choiceformat(choice)} *{poll['choices'][choice]}*\nIn this thread, discuss: {poll['thread_question']}"
            # 	await thread.send(embed=embed)

    class SelfAssignRoleView(discord.ui.View):
        def __init__(self, role_ids):
            super().__init__(timeout=None)
            role_ids.sort()

            self.add_item(
                self.SelfAssignButton(
                    role_ids,
                    label="Get role!",
                    custom_id=",".join(str(i) for i in role_ids),
                )
            )

        class SelfAssignButton(discord.ui.Button):
            def __init__(self, role_ids, **kwargs):
                super().__init__(**kwargs)
                self.role_ids = role_ids

            async def callback(self, interaction: discord.Interaction):
                user = interaction.user

                roles = []
                for r in self.role_ids:
                    role = interaction.guild.get_role(r)
                    if role:
                        roles.append(role)

                rolepings = " ".join(r.mention for r in roles)

                if any(i not in user.roles for i in roles):
                    await user.add_roles(*roles)
                    return await interaction.response.send_message(
                        f"Successfully **gave** you the roles: {rolepings}. Click again to remove.",
                        ephemeral=True,
                    )
                else:
                    await user.remove_roles(*roles)
                    return await interaction.response.send_message(
                        f"Sucessfully **removed** from you these roles: {rolepings}. Click again to re-add.",
                        ephemeral=True,
                    )

    async def on_startup_self_assign(self):
        tags = await self.fetch_all_tags(end_message_self_assign="true")
        tags = [
            t
            for t in tags
            if t["end_message_self_assign"]
            and len(t["end_message_role_ids"]) != 0
        ]

        for t in tags:
            view = self.SelfAssignRoleView(t["end_message_role_ids"])
            self.bot.add_view(view)

    class EditModal(discord.ui.Modal):
        def __init__(self, *, title, texts):
            super().__init__(title=title)

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

    class EditView(discord.ui.View):
        def __init__(self, *, items, modal, groups, title):
            super().__init__(timeout=None)
            self.items = items
            self.modal = modal
            self.msg = None
            self.groups = groups
            self.title = title

            self.interaction = None
            self.status = False

            self.checks = []
            self.incomplete = {}

            self.add_check(
                lambda x: not any(i.required and not i.value for i in x.values()),
                "You have not completed all required fields",
            )

            for k, v in groups.items():
                self.add_item(self.EditButton(select=v, label=k, row=0))

            self.add_item(
                self.ConfirmButton(
                    confirm=True, label="Confirm", style=discord.ButtonStyle.green
                )
            ),
            self.add_item(
                self.ConfirmButton(
                    confirm=False, label="Cancel", style=discord.ButtonStyle.red
                )
            )

            self.check_confirm()

        class EditButton(discord.ui.Button):
            def __init__(self, *, select, **kwargs):
                super().__init__(**kwargs)
                self.select = select

            async def callback(self, interaction: discord.Interaction):
                modal = self.view.modal(
                    title=self.view.title,
                    texts={i: self.view.items[i].text_input() for i in self.select},
                )
                await interaction.response.send_modal(modal)
                await modal.wait()
                for k, v in modal.values.items():
                    self.view.items[k].value = v if v else None
                await self.view.update_message(self.view)
                self.view.check_confirm()
                await self.view.update_view()

        class ConfirmButton(discord.ui.Button):
            def __init__(self, *, confirm, **kwargs):
                super().__init__(**kwargs, custom_id=f"c-{confirm}")
                self.value = confirm

            async def callback(self, interaction: discord.Interaction):
                self.view.status = self.value
                self.view.interaction = interaction
                self.view.stop()

                for child in self.view.children:
                    child.disabled = True

        class IncompleteButton(discord.ui.Button):
            def __init__(self, label):
                super().__init__(disabled=True, label=label)

        async def update_message(self):
            raise NotImplementedError()

        async def update_view(self):
            await self.msg.edit(view=self)

        def check_confirm(self):
            complete = True
            for check, error in self.checks:
                incomplete = not check(self.items)
                complete = complete and not incomplete
                if incomplete and error not in self.incomplete:
                    self.incomplete[error] = next(
                        i
                        for i in self.add_item(self.IncompleteButton(error)).children
                        if i.label == error
                    )
                elif not incomplete and error in self.incomplete:
                    self.remove_item(self.incomplete[error])
                    self.incomplete.pop(error)

            # for child in [c for c in self.children if c.custom_id.split('-')[0] == 'c']:
            for child in [c for c in self.children if c.custom_id == "c-True"]:
                child.disabled = not complete

        def add_check(self, check, error):
            """check() returns True if input is valid"""
            self.checks.append([check, error])

    class EditItem:
        def __init__(
            self,
            *,
            name,
            value=None,
            placeholder=None,
            max_length=None,
            required=True,
            style=discord.TextStyle.short,
        ):
            self.name = name
            self.value = value
            self.placeholder = placeholder
            self.max_length = max_length
            self.required = required
            self.style = style

        def text_input(self):
            return discord.ui.TextInput(
                label=self.name,
                placeholder=self.placeholder,
                default=self.value,
                style=self.style,
                required=self.required,
                max_length=self.max_length,
            )

    def editmodalembed(self, groups, items, *, title, description):
        embed = discord.Embed(title=title, description=description, colour=0x2F3136)

        for k, v in groups.items():
            embed.add_field(
                name=k,
                value="\n".join(
                    f"**{items[i].name}**: {items[i].value if not items[i].required or items[i].value is not None else '__**REQUIRED**__'}"
                    for i in v
                ),
            )

        if "image" in items.keys() and items["image"].value:
            if items["image"].value.lower().startswith("http"):
                embed.set_image(url=items["image"].value)
            else:
                embed.add_field(
                    name="Invalid Image URL",
                    value="That doesn't look like a valid image URL! Make sure you've pasted the image URL correctly!",
                )

        return embed

    @pollsgroup.command(name="create")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(
        question="Main Poll Question to ask.",
        description="Additional notes/description about the question.",
        opt_1="Option 1.",
        opt_2="Option 2.",
        opt_3="Option 3.",
        opt_4="Option 4.",
        opt_5="Option 5.",
        opt_6="Option 6.",
        opt_7="Option 7.",
        opt_8="Option 8.",
        thread_question="Question to ask in the accompanying Thread.",
        image="Image to accompany Poll Question.",
        image_url="Image as URL (alternative to upload)",
        tag="Tag categorising this Poll Question.",
        show_question="Show question in poll message. Defaults to true.",
        show_options="Show options in poll message. Defaults to true.",
        show_voting="Show the current state of votes in poll message. Defaults to true.",
    )
    async def pollscreate(
        self,
        interaction: discord.Interaction,
        question: str = None,
        opt_1: str = None,
        opt_2: str = None,
        tag: str = None,
        description: str = None,
        thread_question: str = None,
        image: Attachment = None,
        image_url: str = None,
        opt_3: str = None,
        opt_4: str = None,
        opt_5: str = None,
        opt_6: str = None,
        opt_7: str = None,
        opt_8: str = None,
        show_question: bool = True,
        show_options: bool = True,
        show_voting: bool = True,
    ):
        """Creates a poll question."""

        await interaction.response.defer()

        choices = [
            i for i in [opt_1, opt_2, opt_3, opt_4, opt_5, opt_6, opt_7, opt_8] if i
        ]

        if image and image.content_type.split("/")[0] == "image":
            image = image.url
        elif image_url:
            image = image_url

        if tag:
            guild_id = await self.fetchguildid(interaction)
            tag = await self.validtag(tag, lambda x: x["guild_id"] == guild_id)
            if tag is None:
                return await interaction.followup.send(
                    "Please select an available tag."
                )
            tag = tag["tag"]

        while True:
            poll_id = random.randint(10000, 99999)
            async with self.acquire_bot_conn() as conn:
                if not conn.fetchrow("SELECT id FROM polls WHERE id = $1", poll_id):
                    break

        # id (int), num (int), time (datetime), message_id (int), question (str), thread_question (str), choices (str[]), votes (int[]), image (str), published (bool), duration (datetime), guild_id (int), description (str), tag (int), show_question (bool), show_options (bool), show_voting (bool), active (bool), crosspost_message_ids (int[])

        poll = {
            "id": poll_id,
            "question": question,
            "published": False,
            "active": False,
            "guild_id": interaction.guild_id,
            "choices": choices,
            "votes": None,
            "time": None,
            "duration": None,
            "num": None,
            "message_id": None,
            "crosspost_message_ids": None,
            "tag": tag,
            "image": image,
            "description": description,
            "thread_question": thread_question,
            "show_question": show_question,
            "show_options": show_options,
            "show_voting": show_voting,
        }

        if question is None or len(choices) < 2:
            groups = {
                "Edit info": ["question", "description", "thread_question", "image"],
                "Edit options (1-4)": [f"opt_{i}" for i in range(1, 4 + 1)],
                "Edit options (5-8)": [f"opt_{i}" for i in range(5, 8 + 1)],
            }

            opt = lambda n, req: self.EditItem(
                name=f"Option #{n}",
                placeholder=f"Type option #{n} here...",
                value=poll["choices"][n - 1] if n <= len(poll["choices"]) else None,
                style=discord.TextStyle.long,
                required=req,
                max_length=self.maxqlength,
            )

            defaultlength = 500
            items = {
                "question": self.EditItem(
                    name="Question",
                    placeholder="Type your question here...",
                    value=poll["question"],
                    style=discord.TextStyle.long,
                    max_length=self.maxqlength,
                ),
                "description": self.EditItem(
                    name="Description",
                    placeholder="Type your description here...",
                    value=poll["description"],
                    style=discord.TextStyle.long,
                    required=False,
                    max_length=defaultlength,
                ),
                "thread_question": self.EditItem(
                    name="Thread Question",
                    placeholder='Type your thread question here... "def" for default msg, empty to ignore.',
                    value=poll["thread_question"],
                    style=discord.TextStyle.long,
                    required=False,
                    max_length=defaultlength,
                ),
                "image": self.EditItem(
                    name="Image URL",
                    placeholder="Paste your image URL here...",
                    value=poll["image"],
                    required=False,
                ),
            } | {f"opt_{n}": opt(n, n in [1, 2]) for n in range(1, 8 + 1)}

            view = self.EditView(
                items=items, modal=self.EditModal, groups=groups, title=f"Create Poll"
            )

            embedtxt = {
                "title": f"Creating Poll",
                "description": "`Tag`, `Show Question`, `Show Options`, and `Show Voting` can only be set via the slash command parameters. These can also be edited later with `/polls edit`.",
            }

            editmodalembed = self.editmodalembed

            async def update_message(self):
                embed = editmodalembed(self.groups, self.items, **embedtxt)
                await self.msg.edit(embed=embed)

            view.update_message = update_message

            msg = await interaction.followup.send(
                embed=editmodalembed(groups, items, **embedtxt), view=view
            )
            view.msg = msg

            await view.wait()
            await msg.edit(view=view)

            interaction = view.interaction
            await interaction.response.defer()

            if not view.status:
                return await msg.edit(content="Cancelled.")

            final = {k: v.value for k, v in view.items.items()}
            final["choices"] = []
            for n in range(1, 8 + 1):
                x = final.pop(f"opt_{n}")
                if x is not None:
                    final["choices"].append(x)

            for k, v in final.items():
                poll[k] = v

            interaction = view.interaction

        if len(poll["question"]) > self.maxqlength:
            return await interaction.followup.send_message(
                f"Question is too long! Must be less than {self.maxqlength} characters."
            )

        async with self.acquire_bot_conn() as conn:
            await conn.execute(
                f"""
                    INSERT INTO polls
                        ({", ".join(poll.keys())})
                    VALUES
                        ({", ".join(f"${i}" for i in range(1, len(poll) + 1))})
                """,
                *poll.values(),
            )

        poll = await self.fetch_poll(poll_id)
        embed = await self.pollinfoembed(poll)

        txt = f"Created new poll question: \"{poll['question']}\""
        if tag is None:
            txt += "\n***WARNING:** This poll does not have a TAG*"

        await interaction.followup.send(txt, embed=embed)

    @pollscreate.autocomplete("tag")
    async def pollscreate_autocomplete_tag(
        self, interaction: discord.Interaction, current: str
    ):
        return await self.autocomplete_tag(interaction, current)

    @pollsgroup.command(name="delete")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(poll_id="5-digit ID of the poll to delete.")
    async def polldelete(self, interaction: discord.Interaction, poll_id: int):
        """Deletes a poll question."""

        await interaction.response.defer()

        poll = await self.fetch_poll(poll_id)

        if not poll or not await self.has_manager_perms_by_user_and_ids(
            interaction.user, poll["guild_id"], interaction.channel_id
        ):
            return await interaction.followup.send(
                f"Couldn't find a poll with the ID `{poll_id}`."
            )

        if poll["published"]:
            return await interaction.followup.send(
                f"This poll has already been published, and cannot be deleted."
            )

        view = self.Confirm()
        embed = await self.pollinfoembed(poll)

        msg = await interaction.followup.send(
            f"Do you want to delete this poll question?", embed=embed, view=view
        )

        await view.wait()

        for child in view.children:
            child.disabled = True

        if view.value is None:
            await msg.edit(content="Timed out.", view=view)
        elif view.value:
            async with self.acquire_bot_conn() as conn:
                await conn.execute("DELETE FROM polls WHERE id = $1", poll_id)
                await conn.execute("DELETE FROM pollsvotes WHERE poll_id = $1", poll_id)

            # tags = await self.fetch_all_tags()
            # findtag = lambda x: next(i for i in tags if i['id'] == x['tag'])
            #
            # recreate = ["/polls create", f"question: {poll['question']}"]
            # recreate += [f"opt_{i}: {c}" for c, i in zip(poll['choices'], range(1, len(poll['choices']) + 1))]
            # if poll['description']: recreate.append(f"question: {poll['description']}")
            # if poll['thread_question']: recreate.append(f"thread_question: {poll['thread_question']}")
            # if poll['image']: recreate.append(f"image: {poll['image']}")
            # if poll['tag']: recreate.append(f"tag: {findtag(poll['tag']).name}")
            # if poll['show_question'] is not None: recreate.append(f"show_question: {poll['show_question']}")
            # if poll['show_options'] is not None: recreate.append(f"show_options: {poll['show_options']}")
            # if poll['show_voting'] is not None: recreate.append(f"show_voting: {poll['show_voting']}")
            # recreatemsg = ' '.join(recreate)

            # await msg.edit(content=f"Deleted the poll question.\n\nTo recreate this poll, type:\n`{recreatemsg}",
            #                view=view)

            await msg.edit(content=f"Deleted the poll question.", view=view)
        else:
            await msg.edit(content="Cancelled.", view=view)

    @polldelete.autocomplete("poll_id")
    async def polldelete_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        return await self.autocomplete_searchbypollid(interaction, current)

    @pollsgroup.command(name="edit")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(
        poll_id="5-digit ID of the poll to edit.",
        question="Main Poll Question to ask.",
        description="Additional notes/description about the question.",
        opt_1="Option 1.",
        opt_2="Option 2.",
        opt_3="Option 3.",
        opt_4="Option 4.",
        opt_5="Option 5.",
        opt_6="Option 6.",
        opt_7="Option 7.",
        opt_8="Option 8.",
        thread_question="Question to ask in the accompanying Thread.",
        image="Image to accompany Poll Question.",
        tag="Tag categorising this Poll Question.",
        show_question="Show question in poll message.",
        show_options="Show options in poll message.",
        show_voting="Show the current state of votes in poll message.",
    )
    async def polledit(
        self,
        interaction: discord.Interaction,
        poll_id: int,
        question: str = None,
        description: str = None,
        thread_question: str = None,
        image: Attachment = None,
        tag: str = None,
        opt_1: str = None,
        opt_2: str = None,
        opt_3: str = None,
        opt_4: str = None,
        opt_5: str = None,
        opt_6: str = None,
        opt_7: str = None,
        opt_8: str = None,
        show_question: bool = None,
        show_options: bool = None,
        show_voting: bool = None,
    ):
        """Edits a poll question. Type '-clear' to clear the current value. You must have a question and at least two options. Leave values empty to keep them the same."""

        await interaction.response.defer()

        poll = await self.fetch_poll(poll_id)

        if not poll or not await self.has_manager_perms_by_user_and_ids(
            interaction.user, poll["guild_id"], interaction.channel_id
        ):
            return await interaction.followup.send(
                f"Couldn't find a poll with the ID `{poll_id}`."
            )
        oldpoll = poll

        if poll["published"] and tag:
            return await interaction.followup.send(
                "You can't edit tags once the poll's been published!"
            )

        if tag:
            guild_id = await self.fetchguildid(interaction)
            tag = await self.validtag(tag, lambda x: x["guild_id"] == guild_id)
            if tag is None:
                return await interaction.followup.send(
                    "Please select an available tag."
                )
            else:
                tag = tag["tag"]

        if all(
            i is None
            for i in [
                question,
                description,
                thread_question,
                image,
                opt_1,
                opt_2,
                opt_3,
                opt_4,
                opt_5,
                opt_6,
                opt_7,
                opt_8,
            ]
        ):

            groups = {
                "Edit info": ["question", "description", "thread_question", "image"],
                "Edit options (1-4)": [f"opt_{i}" for i in range(1, 4 + 1)],
                "Edit options (5-8)": [f"opt_{i}" for i in range(5, 8 + 1)],
            }

            opt = lambda n, req: self.EditItem(
                name=f"Option #{n}",
                placeholder=f"Type option #{n} here...",
                value=poll["choices"][n - 1] if n <= len(poll["choices"]) else None,
                style=discord.TextStyle.long,
                required=req,
                max_length=self.maxqlength,
            )

            defaultlength = 500
            items = {
                "question": self.EditItem(
                    name="Question",
                    placeholder="Type your question here...",
                    value=poll["question"],
                    style=discord.TextStyle.long,
                    max_length=self.maxqlength,
                ),
                "description": self.EditItem(
                    name="Description",
                    placeholder="Type your description here...",
                    value=poll["description"],
                    style=discord.TextStyle.long,
                    required=False,
                    max_length=defaultlength,
                ),
                "thread_question": self.EditItem(
                    name="Thread Question",
                    placeholder='Type your thread question here... "def" for default msg, empty to ignore.',
                    value=poll["thread_question"],
                    style=discord.TextStyle.long,
                    required=False,
                    max_length=defaultlength,
                ),
                "image": self.EditItem(
                    name="Image URL",
                    placeholder="Paste your image URL here...",
                    value=poll["image"],
                    required=False,
                ),
            } | {f"opt_{n}": opt(n, n in [1, 2]) for n in range(1, 8 + 1)}

            view = self.EditView(
                items=items,
                modal=self.EditModal,
                groups=groups,
                title=f"Edit Poll ({poll['id']})",
            )

            embedtxt = {
                "title": f"Editing Poll {poll['id']}",
                "description": "`Tag`, `Show Question`, `Show Options`, and `Show Voting` can only be set via the slash command parameters. Click Confirm if you're only editing those parameters.",
            }

            editmodalembed = self.editmodalembed

            async def update_message(self):
                embed = editmodalembed(self.groups, self.items, **embedtxt)
                await self.msg.edit(embed=embed)

            view.update_message = update_message

            msg = await interaction.followup.send(
                embed=editmodalembed(groups, items, **embedtxt), view=view
            )
            view.msg = msg

            await view.wait()
            await msg.edit(view=view)

            interaction = view.interaction
            await interaction.response.defer()

            if not view.status:
                return await msg.edit(content="Cancelled.")

            final = {k: v.value for k, v in view.items.items()}
            final["choices"] = []
            for n in range(1, 8 + 1):
                x = final.pop(f"opt_{n}")
                if x is not None:
                    final["choices"].append(x)

            for k, v in {
                "tag": tag,
                "show_question": show_question,
                "show_options": show_options,
                "show_voting": show_voting,
            }.items():
                if v is not None:
                    final[k] = v

            txt = [
                f"{k} = ${i}"
                for k, i in zip(final.keys(), list(range(2, len(final) + 2)))
            ]

            async with self.acquire_bot_conn() as conn:
                await conn.execute(
                    f"UPDATE polls SET {', '.join(txt)} WHERE id = $1",
                    poll_id,
                    *final.values(),
                )

        else:
            clearvalue = "-clear"

            if image and image.content_type.split("/")[0] == "image":
                image = image.url

            if question and len(question) > self.maxqlength:
                return await interaction.followup.send_message(
                    f"Question is too long! Must be less than {self.maxqlength} characters."
                )

            choices = []
            choicesmod = [opt_1, opt_2, opt_3, opt_4, opt_5, opt_6, opt_7, opt_8]

            for i in range(len(choicesmod)):
                if i < len(poll["choices"]):
                    old = poll["choices"][i]
                else:
                    old = None
                mod = choicesmod[i]
                if mod == None:
                    choices.append(old)
                elif mod == clearvalue:
                    choices.append(None)
                else:
                    choices.append(mod)
            choices = [i for i in choices if i is not None]

            if poll["published"] and len(choices) != len(poll["choices"]):
                return await interaction.followup.send(
                    "You can't add/remove choices once the poll's been published!"
                )

            if len(choices) < 2:
                return await interaction.followup.send("You need at least 2 choices!")

            async def update(name, *values):
                if not isinstance(name, list):
                    name = [name]
                if len(name) != len(values):
                    raise Exception

                txt = [
                    f"{k} = ${i}" for k, i in zip(name, list(range(1, len(values) + 1)))
                ]

                async with self.acquire_bot_conn() as conn:
                    await conn.execute(
                        f"UPDATE polls SET {', '.join(txt)} WHERE id = ${len(values) + 1}",
                        *values,
                        poll_id,
                    )

            clear = lambda x: None if x == clearvalue else x

            names = []
            values = []

            def append(name, value):
                names.append(name)
                values.append(value)

            if question is not None:
                append("question", question)
            if choices is not None:
                append("choices", choices)
            if description is not None:
                append("description", clear(description))
            if thread_question is not None:
                append("thread_question", clear(thread_question))
            if image is not None:
                append("image", clear(image))
            if tag is not None:
                append("tag", clear(tag))
            if show_question is not None:
                append("show_question", show_question)
            if show_options is not None:
                append("show_options", show_options)
            if show_voting is not None:
                append("show_voting", show_voting)

            await update(names, *values)

        newpoll = await self.fetch_poll(poll_id)

        guild = await self.fetch_guild_info(newpoll["guild_id"])
        tag = await self.fetch_tag(newpoll["tag"])

        oldembed = await self.pollinfoembed(oldpoll, guild=guild, tag=tag)
        newembed = await self.pollinfoembed(newpoll, guild=guild, tag=tag)

        oldembed.title = f"[OLD] {oldembed.title}"
        newembed.title = f"[NEW] {newembed.title}"

        if poll["published"]:
            await self.updatepollmessage(newpoll)

        await interaction.followup.send(
            f"Edited poll `{poll_id}`", embeds=[oldembed, newembed]
        )

    @polledit.autocomplete("poll_id")
    async def polledit_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        results = await self.autocomplete_searchbypollid(
            interaction, current, returnresults=True
        )
        results = [
            i for i in results if not i["published"] or (i["published"] and i["active"])
        ]

        results.sort(key=lambda x: x["published"])

        choices = [
            app_commands.Choice(
                name=self.truncate(
                    f"[{i['id']}] {i['question']}",
                    f"{'{published}' if i['published'] else ''}",
                ),
                value=i["id"],
            )
            for i in results[:25]
        ]
        return choices

    @polledit.autocomplete("tag")
    async def polledit_autocomplete_tag(
        self, interaction: discord.Interaction, current: str
    ):
        return await self.autocomplete_tag(interaction, current, clear="-clear")

    @pollsgroup.command(name="schedule")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(
        poll_id="5-digit ID of the poll to schedule.",
        schedule_time="Scheduled time for the poll to start. Given in Epoch timestamp (UTC). Leave empty if published, or want to leave the scheduled date unchanged. Set to -1 to clear.",
        duration="Duration for poll to run. Can pass Epoch timestamp (UTC) as the ending time instead. Can give number of seconds as raw value. Set to -1 to clear.",
    )
    async def poll_schedule(
        self,
        interaction: discord.Interaction,
        poll_id: int,
        schedule_time: int = None,
        duration: float = None,
    ):
        """Schedules polls for publishing"""

        await interaction.response.defer()

        clearschedule = schedule_time == -1
        if clearschedule:
            schedule_time = None

        end_time = (
            duration
            if duration and duration >= discord.utils.utcnow().timestamp()
            else None
        )
        if end_time:
            duration = None

        poll = await self.fetch_poll(poll_id)

        if not poll or not await self.has_manager_perms_by_user_and_ids(
            interaction.user, poll["guild_id"], interaction.channel_id
        ):
            return await interaction.followup.send(
                f"Couldn't find a poll with the ID `{poll_id}`."
            )

        current = discord.utils.utcnow()

        if poll["published"]:
            if schedule_time:
                return await interaction.followup.send(
                    f"This poll has already been published, therefore the start time cannot be rescheduled."
                )
            else:
                # schedule_time = poll['time'].timestamp()
                schedule_time = current.timestamp()

        if not schedule_time and not poll["published"]:
            if poll["time"]:
                schedule_time = poll["time"].timestamp()

        if clearschedule:
            schedule_time = None
            scheduled = None

        if schedule_time:
            scheduled = _dt.datetime.fromtimestamp(schedule_time, _dt.timezone.utc)

            if end_time:
                end = _dt.datetime.fromtimestamp(end_time, _dt.timezone.utc)
                duration = end_time - scheduled.timestamp()

                if (end_time - schedule_time) < 0:
                    return await interaction.followup.send(
                        f"You're trying to end the poll before it starts! (Starting <t:{int(schedule_time)}:F> but ending <t:{int(end.timestamp())}:F>"
                    )
                elif (end_time - current.timestamp()) < 0:
                    return await interaction.followup.send(
                        f"You're trying to end the poll in the past! <t:{int(end_time)}:F>, <t:{int(end_time)}:R>"
                    )

            if (scheduled - current).total_seconds() < 0:
                return await interaction.followup.send(
                    f"You're trying to schedule a message in the past! <t:{int(schedule_time)}:F>, <t:{int(schedule_time)}:R>"
                )

        else:
            if end_time:
                return await interaction.followup.send(
                    "You can't set an end time without a start time!"
                )

        if not poll["published"] and (schedule_time != poll["time"] or clearschedule):
            await self.bot.polls_api.update_polls(
                [
                    {
                        "id": poll_id,
                        "question": poll["question"],
                        "choices": poll["choices"],
                        "start_time": scheduled.isoformat() if scheduled else None,
                    }
                ],
                interaction.user.id,
            )

            if poll["time"]:
                if not clearschedule:
                    await self.schedule_starts(
                        timestamps=[schedule_time, poll["time"].timestamp()]
                    )
                else:
                    await self.schedule_starts(timestamps=[poll["time"].timestamp()])
            elif not clearschedule:
                await self.schedule_starts(timestamps=[schedule_time])

        if duration:
            if duration == -1:
                end = None
            elif poll["published"]:
                end = discord.utils.utcnow() + _dt.timedelta(seconds=duration)
            else:
                end = poll["time"] + _dt.timedelta(seconds=duration)
            await self.bot.polls_api.update_polls(
                [
                    {
                        "id": poll_id,
                        "question": poll["question"],
                        "choices": poll["choices"],
                        "end_time": end.isoformat() if end else None,
                    }
                ],
                interaction.user.id,
            )

            await self.schedule_ends(poll_ids=[poll_id])

        poll = await self.fetch_poll(poll_id)

        embed = discord.Embed(
            title="Scheduled Poll",
            description=f"{poll['question']}",
            colour=await self.fetchcolourbyid(poll["guild_id"], poll["tag"]),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(
            text=f"ID: {poll['id']}"
            + f"""{f" (#{poll['num']})" if poll['num'] else ""}"""
        )
        embed.add_field(
            name="Start time",
            value=(
                f"<t:{int(poll['time'].timestamp())}:F>\n`{int(poll['time'].timestamp())}`"
                if poll["time"]
                else "No time scheduled."
            ),
        )
        embed.add_field(
            name="End time",
            value=(
                f"<t:{int((poll['time'] + poll['duration']).timestamp())}:F> - lasts {self.strfduration(poll['duration'])}\n`{int(poll['duration'].total_seconds())}`"
                if poll["time"] and poll["duration"]
                else (
                    f"Lasts {poll['duration']}\n`{int(poll['duration'].total_seconds())}`"
                    if poll["duration"]
                    else "No end time scheduled."
                )
            ),
        )

        return await interaction.followup.send(embed=embed)

    @poll_schedule.autocomplete("poll_id")
    async def pollschedule_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        results = await self.autocomplete_searchbypollid(
            interaction, current, returnresults=True
        )
        results = [
            i for i in results if not i["published"] or (i["published"] and i["active"])
        ]

        results.sort(
            key=lambda x: x["time"].timestamp() if x["time"] is not None else -1
        )
        results.sort(key=lambda x: x["published"])

        choices = [
            app_commands.Choice(
                name=self.truncate(
                    f"[{i['id']}] {i['question']}",
                    f"{'{published}' if i['published'] else ('{scheduled}' if i['time'] else '')}",
                ),
                value=i["id"],
            )
            for i in results[:25]
        ]
        return choices

    @poll_schedule.autocomplete("duration")
    async def pollschedule_autocomplete_duration(
        self, interaction: discord.Interaction, current: float
    ):
        return await self.autocomplete_duration(interaction, current, clear=-1)

    @poll_schedule.autocomplete("schedule_time")
    async def pollschedule_autocomplete_schedule_time(
        self, interaction: discord.Interaction, current: int
    ):
        choices = []
        if current.isdigit() and int(current) == -1 or not current:
            choices += [app_commands.Choice(name=f"Clear scheduled time.", value=-1)]
        timestamp = TimeCog.strtodatetime(TimeCog, current)
        choices += [
            app_commands.Choice(name=self.strf(t), value=int(t.timestamp()))
            for t in timestamp
        ]
        return choices[:25]

    @pollsgroup.command(name="start")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(
        poll_id="5-digit ID of the poll to start.",
        duration="Duration for poll to run. Can pass Epoch timestamp (UTC) as the ending time instead. Can give number of seconds as raw value.",
    )
    async def pollstart(
        self, interaction: discord.Interaction, poll_id: int, duration: int = None
    ):
        """Starts the voting for a poll question."""

        await interaction.response.defer()

        poll = await self.fetch_poll(poll_id)

        if not poll or not await self.has_manager_perms_by_user_and_ids(
            interaction.user, poll["guild_id"], interaction.channel_id
        ):
            return await interaction.followup.send(
                f"Couldn't find a poll with the ID `{poll_id}`."
            )

        if poll["published"]:
            return await interaction.followup.send(
                f"This poll has already been published!"
            )

        current = discord.utils.utcnow()
        end_time = duration if duration and duration >= current.timestamp() else None
        if end_time:
            end = _dt.datetime.fromtimestamp(end_time, _dt.timezone.utc)
            duration = end_time - current.timestamp()

            if duration < 0:
                return await interaction.followup.send(
                    f"You're trying to end the poll in the past! <t:{int(end_time)}:F>, <t:{int(end_time)}:R>"
                )
        else:
            end = None

        currenttime = discord.utils.utcnow()

        if duration:
            durationtimedelta = _dt.timedelta(seconds=duration)
            async with self.acquire_bot_conn() as conn:
                await conn.execute(
                    "UPDATE polls SET time = $2, duration = $3 WHERE id = $1",
                    poll_id,
                    discord.utils.utcnow(),
                    durationtimedelta,
                )

        result = await self.startpoll(poll["id"], set_time=currenttime)

        if result:
            msglinks = "\n".join(
                [
                    f"{msg.channel.mention} [{poll['question']}](<{msg.jump_url}>)"
                    for poll, msg in result
                ]
            )
            return await interaction.followup.send(
                f"Successfully started the poll!\n{msglinks}"
            )
        else:
            raise Exception

    @pollstart.autocomplete("poll_id")
    async def pollstart_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        return await self.autocomplete_searchbypollid(
            interaction, current, published=False
        )

    @pollstart.autocomplete("duration")
    async def pollstart_autocomplete_duration(
        self, interaction: discord.Interaction, current: float
    ):
        return await self.autocomplete_duration(interaction, current)

    @pollsgroup.command(name="end")
    @poll_manager_only()
    @valid_guild_only()
    @app_commands.describe(poll_id="5-digit ID of the poll to end.")
    async def pollend(self, interaction: discord.Interaction, poll_id: int):
        """Ends the voting for a poll question."""

        await interaction.response.defer()

        poll = await self.fetch_poll(poll_id)

        if not poll or not await self.has_manager_perms_by_user_and_ids(
            interaction.user, poll["guild_id"], interaction.channel_id
        ):
            return await interaction.followup.send(
                f"Couldn't find a poll with the ID `{poll_id}`."
            )

        if not poll["active"]:
            return await interaction.followup.send(f"This poll is not active!")

        await self.endpoll(poll["id"], set_time=True)

        await interaction.followup.send(f"Successfully ended the poll!")

    @pollend.autocomplete("poll_id")
    async def pollend_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        return await self.autocomplete_searchbypollid(interaction, current, active=True)

    @pollsgroup.command(name="search")
    @valid_guild_only()
    @app_commands.describe(
        poll_id="ID (5-digit or #) of the poll to search for.",
        keyword="Keyword to search for. Searches the question and thread question. Case-insensitive.",
        sort="Order to list results.",
        tag="Tag to filter results by.",
        active="List active or inactive questions only.",
        published="List published or unpublished questions only. Unpublished polls are only visible to Poll Managers.",
        showextrainfo="Shows all settings for the poll. Only useable by Poll Managers.",
    )
    @app_commands.choices(sort=choices["sort"])
    async def pollsearch(
        self,
        interaction: discord.Interaction,
        poll_id: int = None,
        keyword: str = None,
        sort: Choice[str] = None,
        tag: str = None,
        active: bool = None,
        published: bool = None,
        showextrainfo: bool = False,
    ):
        """Searches poll questions. Search by poll ID, or by keyword, and filter by tag."""

        await interaction.response.defer()

        # Defaults
        if sort is None:
            if published == False:
                sort = self.Sort.oldest.name
            else:
                sort = self.Sort.newest.name

        sort = self.Sort.__members__[sort.value if not isinstance(sort, str) else sort]

        if poll_id:
            poll = await self.fetch_poll(poll_id)

            if not poll:
                matches = await self.bot.polls_api.sync_all_polls(guildId=interaction.guild_id, num=poll_id)
                poll = self.poll_dict(matches[0]) if matches else None

            managerperms = await self.hasmanagerperms(interaction)

            if not poll or (
                not poll["published"]
                and not managerperms
                and await self.canview(poll, interaction.guild_id)
            ):
                return await interaction.followup.send(
                    f"Couldn't find a poll with the ID `{poll_id}`."
                )

            if showextrainfo:
                if not managerperms:
                    showextrainfo = False

            if not showextrainfo:
                embed = await self.pollquestionembed(
                    poll, interaction=interaction, showextra=True
                )
            else:
                embed = await self.pollinfoembed(poll)

            await interaction.followup.send(embed=embed)
            return

        else:
            notag = "-1"
            # if tag:
            # 	if (not tag.isdigit() or not await self.fetch_tag(int(tag))) and not tag == notag:
            # 		return await interaction.followup.send("Please select an available tag.")
            # 	else:
            # 		tag = int(tag)
            if tag and tag != notag:
                tag = await self.validtag(tag)
                if tag is None:
                    return await interaction.followup.send(
                        "Please select an available tag."
                    )
                else:
                    tag = tag["tag"]

            params = {}
            text = []
            if keyword:
                text.append(f"Keyword search: `{keyword}`")
            if tag:
                if tag != int(notag):
                    params["tag"] = tag
                    text.append(f"Tag: `{await self.tagname(tag)}`")
                else:
                    text.append(f"Tag: None")
            if published is not None:
                text.append(f"Published? `{published}`")
            if active is not None:
                text.append(f"Active? `{active}`")
            if sort:
                text.append(f"Sorted by `{sort.name}`")

            guildid = await self.fetchguildid(interaction)

            polls = await self.bot.polls_api.sync_all_polls(guildId=guildid, **params)
            polls = [
                self.poll_dict(p)
                for p in polls
                if self.search_matches(p, tag, published, active, notag)
            ]

            if keyword:
                polls = self.keywordsearch(keyword, polls)

            polls = [i for i in polls if await self.canview(i, interaction.guild_id)]
            if not await self.hasmanagerperms(interaction):
                polls = [i for i in polls if i["published"]]
            polls = self.sortpolls(polls, sort)

            if not polls:
                return await interaction.followup.send("No results found!")

            msg = await interaction.followup.send("Searching...")

            class PollSearchPaginator(BaseButtonPaginator):
                text = None
                colour = None

                async def format_page(self, entries):
                    def entry_format(poll):
                        string_builder = []
                        string_builder.append("- ")
                        string_builder.append(f"`{poll['id']}`")
                        if poll["num"]:
                            string_builder.append(f" (`#{poll['num']}`)")
                        string_builder.append(f": {poll['question']}")
                        if poll["time"]:
                            string_builder.append(
                                f" (<t:{int(poll['time'].timestamp())}:d>)"
                            )
                        return "".join(string_builder)

                    results = [entry_format(i) for i in entries]
                    results_text = "## Results\n" + "\n".join(results)
                    embed = discord.Embed(
                        title="Polls Search",
                        description="\n".join(self.text + [results_text]),
                        colour=self.colour,
                        timestamp=discord.utils.utcnow(),
                    )

                    embed.set_footer(
                        text=f"Page {self.current_page}/{self.total_pages} ({len(self.entries)} results)"
                    )

                    return embed

            PollSearchPaginator.text = text
            PollSearchPaginator.colour = await self.fetchcolourbyid(
                await self.fetchguildid(interaction), None
            )

            paginator = await PollSearchPaginator.start(msg, entries=polls, per_page=20)
            await paginator.wait()

            for child in paginator.children:
                child.disabled = True
            paginator.stop()

            return await paginator.msg.edit(content="Timed out.", view=paginator)

    @pollsearch.autocomplete("poll_id")
    async def pollsearch_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        return await self.autocomplete_searchbypollid(
            interaction, current, crosspost=True
        )

    @pollsearch.autocomplete("tag")
    async def pollsearch_autocomplete_tag(
        self, interaction: discord.Interaction, current: str
    ):
        return await self.autocomplete_tag(
            interaction, current, clear="-1", clearname="No tag."
        )

    @pollsgroup.command(name="me")
    @valid_guild_only()
    @app_commands.describe(
        show_unvoted="Shows all the polls you haven't voted on yet!",
        user="Views history of a specified user.",
        poll_id="Shows your vote on a specific poll.",
    )
    async def pollsme(
        self,
        interaction: discord.Interaction,
        show_unvoted: bool = False,
        user: discord.User = None,
        poll_id: int = None,
    ):
        """Shows your poll voting history"""

        await interaction.response.defer()

        msg = await interaction.followup.send("Searching...")

        op = True
        if user is None:
            user = interaction.user
        else:
            op = False

        votes = {v.poll_id: v.choice for v in await self.bot.polls_api.get_user_votes(user.id)}

        if poll_id is None:
            if not show_unvoted:
                poll_ids = list(votes.keys())

                if poll_ids:
                    guildid = await self.fetchguildid(interaction)
                    polls = await self.bot.polls_api.sync_all_polls(guildId=guildid, ids=",".join(str(i) for i in poll_ids))
                else:
                    polls = []
                polls = [self.poll_dict(p) for p in polls]
                polls = [
                    i for i in polls if await self.canview(i, interaction.guild_id)
                ]
                polls = self.sortpolls(polls, self.Sort.newest)

                entries = [[i, votes[i["id"]]] for i in polls]

                if not entries:
                    embed = discord.Embed(
                        title=f"{user.name}'s Polls",
                        colour=await self.fetchcolourbyid(
                            await self.fetchguildid(interaction), None
                        ),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.add_field(
                        name="No votes",
                        value=f"{'''You haven't''' if op else f'''{user.name} hasn't'''} voted for anything yet!"
                        + (
                            f"Use `/pollsme show_unvoted: true` to see all the polls you're able to vote on!"
                            if op
                            else ""
                        ),
                    )
                    embed.set_footer(text=f"Page 0/0 (0 results) | {user.id}")
                    return await msg.edit(embed=embed)

                class PollsMePaginator(BaseButtonPaginator):
                    async def format_page(self, entries):
                        embed = discord.Embed(
                            title=f"{self.user.name}'s Polls",
                            colour=self.colour,
                            timestamp=discord.utils.utcnow(),
                        )
                        for p, v in entries:
                            embed.add_field(
                                name=f"{p['id']}{(' (#' + str(p['num']) + ')') if p['num'] else ''}: {p['question']}",
                                value=f"{'You' if self.op else self.user.name} voted: {self.client.choiceformat(v)} "
                                + (f"*{p['choices'][v]}*" if p["show_options"] else ""),
                                inline=False,
                            )
                        embed.set_footer(
                            text=f"Page {self.current_page}/{self.total_pages} ({len(self.entries)} results) | {self.user.id}"
                        )
                        return embed

            else:
                guildid = await self.fetchguildid(interaction)
                guild = await self.fetch_guild_info(guildid)
                tags = {t["tag"]: t for t in await self.fetch_all_tags()}
                polls = await self.bot.polls_api.sync_all_polls(guildId=guildid, live="true")
                polls = [self.poll_dict(p, tags.get(p.tag), guild) for p in polls]
                polls = [poll for poll in polls if poll["published"]]
                polls = [
                    i
                    for i in polls
                    if i["id"] not in votes.keys()
                    and await self.canview(i, interaction.guild_id)
                ]
                polls = self.sortpolls(polls, self.Sort.newest)

                entries = polls

                if not entries:
                    embed = discord.Embed(
                        title=f"{user.name}'s Polls",
                        colour=await self.fetchcolourbyid(
                            await self.fetchguildid(interaction), None
                        ),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.add_field(
                        name="All voted for!",
                        value=f"{'''You've''' if op else f'''{user.name}'s'''} voted on all active polls!",
                    )
                    embed.set_footer(text=f"Page 0/0 (0 results) | {user.id}")
                    return await msg.edit(embed=embed)

                class PollsMePaginator(BaseButtonPaginator):
                    async def format_page(self, entries):
                        embed = discord.Embed(
                            title=f"{self.user.name}'s Polls",
                            colour=self.colour,
                            timestamp=discord.utils.utcnow(),
                        )
                        for p in entries:
                            tag = await self.client.fetch_tag(p["tag"])
                            if interaction.guild_id == p["guild_id"]:
                                message = await self.client.fetchpollmsg(p)
                            else:
                                i = tag["crosspost_servers"].index(interaction.guild_id)
                                message = await self.client.bot.get_channel(
                                    tag["crosspost_channels"][i]
                                ).fetch_message(p["crosspost_message_ids"][i])
                            embed.add_field(
                                name=f"{p['id']}{(' (#' + str(p['num']) + ')') if p['num'] else ''}: {p['question']}",
                                value=f"Vote [here](<{message.jump_url}>)!",
                                inline=False,
                            )
                        embed.set_footer(
                            text=f"Page {self.current_page}/{self.total_pages} ({len(self.entries)} results) | {self.user.id}"
                        )
                        return embed

            PollsMePaginator.user = user
            PollsMePaginator.colour = await self.fetchcolourbyid(
                await self.fetchguildid(interaction), None
            )
            PollsMePaginator.op = op
            PollsMePaginator.interaction = interaction
            PollsMePaginator.client = self

            paginator = await PollsMePaginator.start(msg, entries=entries, per_page=15)

            await paginator.wait()

            for child in paginator.children:
                child.disabled = True
            paginator.stop()

            return await paginator.msg.edit(content="Timed out.", view=paginator)

        else:
            poll = await self.fetch_poll(poll_id)
            if not poll:
                return await interaction.followup.send(
                    f"Couldn't find a poll with the ID `{poll_id}`."
                )

            embed = discord.Embed(
                title=f"{user.name}'s Polls",
                colour=await self.fetchcolourbyid(
                    await self.fetchguildid(interaction), None
                ),
                timestamp=discord.utils.utcnow(),
            )

            # choice = votes[int(poll_id)]
            # if choice is not None:
            if poll["id"] in votes.keys():
                choice = votes[poll["id"]]
                value = (
                    f"{'You' if op else user.name} voted: {self.choiceformat(choice)} "
                    + (f"*{poll['choices'][choice]}*" if poll["show_options"] else "")
                )
            else:
                value = f"{'''You haven't''' if op else f'''{user.name} hasn't'''} voted on this poll yet!"

            embed.add_field(
                name=f"{poll['id']}{(' (#' + str(poll['num']) + ')') if poll['num'] else ''}: {poll['question']}",
                value=value,
                inline=False,
            )

            embed.set_footer(text=str(user.id))

            await msg.edit(content="", embed=embed)

    @pollsme.autocomplete("poll_id")
    async def pollsme_autocomplete_poll_id(
        self, interaction: discord.Interaction, current: int
    ):
        return await self.autocomplete_searchbypollid(
            interaction, current, published=True, crosspost=True
        )

    @pollsgroup.command(name="bulkedit")
    @poll_manager_only()
    @valid_guild_only()
    async def pollbulkedit(
        self,
        interaction: discord.Interaction,
        tag: str,
        show_question: bool = None,
        show_options: bool = None,
        show_voting: bool = None,
    ):
        """Bulk edits a set of poll questions in a tag."""

        await interaction.response.defer()

        if all(i == None for i in [show_question, show_options, show_voting]):
            return await interaction.followup.send("You're not editing anything!")

        guild_id = await self.fetchguildid(interaction)
        tag = await self.validtag(tag, lambda x: x["guild_id"] == guild_id)
        if tag is None:
            return await interaction.followup.send("Please select an available tag.")

        async def update(name, *values):
            if not isinstance(name, list):
                name = [name]
            if len(name) != len(values):
                raise Exception

            txt = [f"{k} = ${i}" for k, i in zip(name, list(range(2, len(values) + 2)))]

            async with self.acquire_bot_conn() as conn:
                await conn.execute(
                    f"UPDATE polls SET {', '.join(txt)} WHERE tag = $1",
                    tag["tag"],
                    *values,
                )

        names = []
        values = []

        def append(name, value):
            names.append(name)
            values.append(value)

        txt = ["Updating polls:"]

        if show_question is not None:
            append("show_question", show_question)
            txt.append(f"`show_question = {show_question}`")
        if show_options is not None:
            append("show_options", show_options)
            txt.append(f"`show_options = {show_options}`")
        if show_voting is not None:
            append("show_voting", show_voting)
            txt.append(f"`show_voting = {show_voting}`")
        txt.append("")

        await update(names, *values)

        async with self.acquire_bot_conn() as conn:
            polls = await conn.fetch("SELECT * FROM polls WHERE tag = $1", tag["tag"])

        for poll in polls:
            txt.append(f"- `{poll['id']}` {poll['question']}")
        txt.append("")

        msg = await interaction.followup.send("\n".join(txt + ["*Updating...*"]))

        for poll in polls:
            await self.updatepollmessage(poll)

    # await msg.edit(content = "\n".join(txt + ["*Updated!*"]))

    @pollbulkedit.autocomplete("tag")
    async def pollbulkedit_autocomplete_tag(
        self, interaction: discord.Interaction, current: str
    ):
        return await self.autocomplete_tag(interaction, current)

    @pollsadmingroup.command(name="sync")
    @app_commands.describe(
        include_ended="Update all messages, including inactive polls.",
        tag="Tag to update.",
    )
    @owner_only()
    async def polladminsync(
        self,
        interaction: discord.Interaction,
        include_ended: bool = False,
        tag: str = None,
    ):
        """Force sync all automated poll routines"""
        await interaction.response.defer()

        if tag:
            guild_id = await self.fetchguildid(interaction)
            tag = await self.validtag(tag, lambda x: x["guild_id"] == guild_id)
            if tag is None:
                return await interaction.followup.send(
                    "Please select an available tag."
                )
            else:
                tag = tag["tag"]

        print("~~~ Running SYNC ~~~")

        tasks = {
            k: {"txt": v, "status": False}
            for k, v in {
                "start_schedule": "Start schedules",
                "end_schedule": "End schedules",
                "update_msg": "Update poll messages",
                "update_selfassign": "Update self-assign buttons",
            }.items()
        }

        async def update():
            await msg.edit(content=generate_txt())

        def generate_txt():
            txt = ["Syncing..."]
            x = {True: "x", False: "-", None: "~"}
            for t in tasks.values():
                txt.append(f"`{x[t['status']]}` {t['txt']}")
            return "\n".join(txt)

        def start(key):
            tasks[key]["status"] = None

        def end(key):
            tasks[key]["status"] = True

        async def task(function, key):
            start(key)
            await update()

            await function()

            end(key)
            await update()

        msg = await interaction.followup.send(generate_txt())

        refreshpolls = lambda: self.search_polls_by_keyword("")
        polls = await refreshpolls()

        await task(self.schedule_starts, "start_schedule")

        await task(self.schedule_ends, "end_schedule")

        async def update_msg():
            pollfilter = "published" if include_ended else "active"
            filtered = [i for i in polls if i[pollfilter]]
            if tag:
                filtered = [i for i in polls if i["tag"] == tag]
            filtered.sort(key=lambda x: discord.utils.utcnow() - x["time"])
            filtered.sort(key=lambda x: not x["active"])
            for poll in filtered:
                await self.do_updatepollmessage(poll, force=poll["active"])

        await task(update_msg, "update_msg")

        async def update_selfassign():
            await self.on_startup_self_assign()

        await task(update_selfassign, "update_selfassign")

        # polls = await refreshpolls()

        print("~~~ End SYNC ~~~")

    @polladminsync.autocomplete("tag")
    async def polladminsync_autocomplete_tag(
        self, interaction: discord.Interaction, current: str
    ):
        return await self.autocomplete_tag(interaction, current)


async def setup(bot):
    await bot.add_cog(PollsCog(bot))
