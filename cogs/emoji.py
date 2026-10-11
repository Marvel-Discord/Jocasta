import math

import discord
from discord.ext import commands
from loguru import logger
from natsort import natsorted

# from config import TESTING_GUILD

import datetime


class EmojiCog(commands.Cog, name="Emoji"):
    """Emoji commands"""

    def __init__(self, bot):
        self.bot = bot

        self.bot.emojiids = [484510768293740577, 484506523809349633, 409904350530371587, 567907688261091343,
                             1164012436895055912, 764798367539920946, 808924000100548648, 854307913580937236,
                             897260541138075669, 854698557406838784, 764739176733474877, 920268012563623936]

    """
    /emoji list
    /emoji members    (include list of Nitro users)

    /emoji infoupdate [guild: all]

    /emoji bpfont <text>

    Emoji changelog

    /hashflags list
    /hashflags add <emoji> <aliases list>
    /hashflags delete <emoji>
    /hashflags append <emoji> <aliases list>
    /hashflags remove <emoji> <aliases list>
    /hashflags replace <emoji> <emoji>
    Hashflags on message and edit
    SQL columns: emoji name, emoji id, triggers (list)
    """

    # all old code below

    ordinal = lambda self, n: "%d%s" % (n, "tsnrhtdd"[(math.floor(n / 10) % 10 != 1) * (n % 10 < 4) * n % 10::4])

    def cint(self, codeinfo):
        return "{:,}".format(codeinfo)

    def strfdelta(self, tdelta, fmt):
        d = {"days": tdelta.days}
        d["hours"], rem = divmod(tdelta.seconds, 3600)
        d["minutes"], d["seconds"] = divmod(rem, 60)
        return fmt.format(**d)

    def s(self, n: int):
        return 's' if n != 1 else ''

    @commands.group()
    async def emoji(self, ctx):
        """Emoji command group"""
        pass

    @emoji.command(name="list")
    @commands.is_owner()
    async def emojilist(self, ctx):
        """Lists all emojis in the current server"""
        emojis = natsorted(list(ctx.guild.emojis), key=lambda item: item.name)
        msg = []
        for emoji in emojis:
            msg.append(f'{str(emoji)} - `:{emoji.name}:`')

        msga = []
        for item in msg:
            if len(msga) == 15:
                await ctx.send('\n'.join(msga))
                msga = []
            msga.append(item)
        if len(msga) != 0: await ctx.send('\n'.join(msga))

        await ctx.send(' '.join([str(emoji) for emoji in emojis]))

    @emoji.command(name='infoupdate')
    @commands.is_owner()
    async def emojiinfo(self, ctx):
        """Updates the emoji pack info in the Nitro Marvel Twitter Emoji pack servers"""
        for serverid in self.bot.emojiids:
            server = self.bot.get_guild(serverid)
            info = discord.utils.get(server.text_channels, name="info")

            await info.purge(limit=100)

            invites = ['https://discord.gg/wpFbuE9', 'https://discord.gg/cBbyQRs', 'https://discord.gg/qg3JxhR',
                       'https://discord.gg/gHbZJkY', 'https://discord.gg/mZ4eScyPpy', 'https://discord.gg/uTgPHK5', 'https://discord.gg/RWEkNcGthX',
                       'https://discord.gg/XYnCxUsEeu', 'https://discord.gg/e39cCVBP5X',
                       'https://discord.gg/w3McMTwNQe', 'https://discord.gg/pJHyQd8', 'https://discord.gg/ApZhV3vV8D']
            # invitestr = '\n'.join(f" - {x}" for x in invites)
            invitestr = ' - '.join(invites)

            aemsg, aei = await self.allemojis()

            msg = [
                '<:bpN:416827915775377408><:bpI:416832557724991508><:bpT:416828506199293972><:bpR:416828411743436810><:bpO:416828042824908802>         <:bpM:416827478443556864><:bpA:416826786975055872><:bpR:416828411743436810><:bpV:416828622637105194><:bpE:416827201321828362><:bpL:416827477529329665>         <:bpT:416828506199293972><:bpW:416829037114032149><:bpI:416832557724991508><:bpT:416828506199293972><:bpT:416828506199293972><:bpE:416827201321828362><:bpR:416828411743436810>         <:bpE:416827201321828362><:bpM:416827478443556864><:bpO:416828042824908802><:bpJ:416827394981101570><:bpI:416832557724991508>',
                'These servers are for use of all the Marvel emojis used as Twitter hashflags and Instagram stickers, as made by *@100soft*. See their Twitter here: <https://twitter.com/100soft>',
                f'The servers contain a total of **{aei}** emoji!',
                f'Join all **{len(invites)}** emote servers - \n{invitestr}',
                'Join the **Marvel Discord** - https://discord.gg/marvel',
                'Join the Black Panther font server - <https://discord.gg/h6FQUbJ>',
                'I recommend checking out 100soft\'s own server! - https://discord.gg/100soft',
                'These emojis can only be used with **Discord Nitro**. [Read more about Discord Nitro](<https://discordapp.com/nitro/>)',
            ]
            infomsg = await info.send('\n'.join(msg))

            for msg in aemsg: await info.send(msg)

            # await info.send(f"(Scroll to the top of the channel to see all the server invites!)")
            await info.send(f">> [Jump to the top!]({infomsg.jump_url}) <<")

            if serverid == self.bot.emojiids[0]:
                allemoji = discord.utils.get(server.text_channels, name="all-emoji")
                await allemoji.purge(limit=100)
                for n, sid in enumerate(self.bot.emojiids):
                    await allemoji.send(f"# {self.bot.get_guild(sid).name}\n{invites[n]}")
                    for msg in (await self.allemojis([sid]))[0]: await allemoji.send(msg)
                    await allemoji.send(f"------------------------------------------------")

            elist = discord.utils.get(server.text_channels, name="emoji-list")

            await elist.purge(limit=100)

            emojis = natsorted(list(server.emojis), key=lambda item: item.name)
            msg = [f'{str(emoji)} - `:{emoji.name}:`' for emoji in emojis]

            msga = []
            for item in msg:
                if len(msga) == 15:
                    await elist.send('\n'.join(msga))
                    msga = []
                msga.append(item)
            if len(msga) != 0: await elist.send('\n'.join(msga))

            # await elist.send(' '.join([str(emoji) for emoji in emojis]))
            for msg in (await self.allemojis(serverid))[0]: await elist.send(msg)

            # https://discord.gg/wpFbuE9
            # https://discord.gg/cBbyQRs
            # https://discord.gg/qg3JxhR
            # https://discord.gg/gHbZJkY
            # https://discord.gg/marvel

            await ctx.send(f'Done ({server.name})')

    @emoji.command(name='members')
    @commands.is_owner()
    async def emojimembers(self, ctx):
        try:
            await ctx.send(
                ', '.join([str(self.bot.get_guild(serverid).member_count) for serverid in self.bot.emojiids]))
        except Exception:
            await ctx.send("Something went wrong")
            logger.exception("failed to get emoji server member counts")

    async def allemojis(self, sid=None, length=12):
        if sid is None: sid = self.bot.emojiids
        if type(sid) == int: sid = [sid]
        emojis = []
        for serverid in sid:
            server = self.bot.get_guild(serverid)
            emojis = emojis + [str(emoji) for emoji in natsorted(list(server.emojis), key=lambda item: item.name)]

        msgs = []
        msg = []
        for item in emojis:
            if len(msg) == length:
                msgs.append(' '.join(msg))
                msg = []
            msg.append(item)
        if len(msg) != 0: msgs.append(' '.join(msg))

        return msgs, len(emojis)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        if guild.id not in self.bot.emojiids: return

        newemojis = [e for e in after if e.id not in [be.id for be in before]]

        if not newemojis: return

        logch = self.bot.get_channel(484511499327635487)
        for newemoji in newemojis: await logch.send(f'<:bp_PLUS:416829422990262303> {str(newemoji)}')

    @emoji.command()
    async def bpfont(self, ctx, *, text: str):
        """Turns text into the Black Panther font"""
        lemojis = self.bot.get_guild(416824873000763423).emojis
        letters = {}
        for e in lemojis: letters[e.name.replace('bp', '').lower()] = f'<:{e.name}:{e.id}>'
        letters[' '] = '         '

        newtext = []
        for l in text:
            if l.lower() in letters.keys():
                newtext.append(letters[l.lower()])
            else:
                newtext.append(l)

        await ctx.send(''.join(newtext))

    @emoji.command()
    async def loadhashflags(self, ctx):
        await self._loadhashflags()
        await ctx.reply("Done")

    async def _loadhashflags(self):
        await self.bot.wait_until_ready()
        self.hashflags = {}

        for serverid in self.bot.emojiids:
            server = self.bot.get_guild(serverid)
            for emoji in server.emojis:
                self.hashflags[str(emoji)] = [emoji.name, emoji.name.replace('_', '')]

        channel = self.bot.get_channel(808887539418529833)
        async for m in channel.history(limit=None):
            contents = m.content.split(' ')
            emoji = contents[0]
            hashflags = contents[1:]
            self.hashflags[emoji] += hashflags

    @emoji.command()
    async def unloadhashflags(self, ctx):
        self.hashflags = {}
        await ctx.reply("Ok, done")


async def setup(bot):
    await bot.add_cog(EmojiCog(bot))
