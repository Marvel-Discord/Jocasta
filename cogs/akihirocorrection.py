from discord.ext import commands
from discord import Embed, Forbidden
from discord import TextChannel, Thread
import time
import re

class AkihiroCog(commands.Cog) :
    def __init__(self, bot) :
        self.bot = bot
      
        # Message
        self.akihiro_message = Embed(
            description=(
                "Please do not use the name 'Daken' as this is actually a slur.\n"
                "Instead, use one of these alternatives: Akihiro, Dark Wolverine, Hellverine, Fang."
            ),
        )

        # Ignored channels and forums
        self.ignored_channels = {
          1109693299297632328, # rules
          1110214786223968346, # announcements
          1109021470736252938, # comic news
          1109021386015522816, # movie tv news
          1109021556371378239, # misc news
          1109728410894356500, # server affiliates
          1109722494002286642, # resource server info
          1109722813058777148, # resource faq
          1109723001836011621, # resource contact staff
          1109723183612964864, # resource ban appeals
          1109723343814406224, # resource spoiler archive
          1109723474177560647, # resource activities
          1108985848558534789, # staff room
          1328965818490294332, # manager room
          1328709586554851359, # mod room
          1109011915402903612, # staff log
          1108992635957416016, # staff bot commands
          1109033106431811664, # automod log
          1207619588565499924, # murderworld
          1382732564610945194, # comic review corner
          1362621880779014397, # bookclub organising (thread)
          1109032560471842826, # polls
          1109032581233659904, # special polls
          1214133803107491840, # polls archive
          1109023403060506634, # polls management
          1252175705480106015, # polls contributors
          1109726177964331148, # tykhe announcements
          1109726240803405894, # tykhe shop
          1109726292208779385, # tykhe rolling
          1110217807116906507, # tykhe rolling 2
          1111142854186762271, # tykhe roll nft
          1109727103722729573, # tykhe commands
          1110217858446790656, # tykhe commands 2
          1111141979376582729, # tykhe trade board
          1109727127051440148, # tykhe discussion
          1108993540463284274, # carl logs
          1110536802638512239, # member log
          1119123107848933416, # carl archive log
          1264919405071040593, # spoiler filter log
          1475009747693342770, # kiai log
          1478668829700657253, # userbot log
        }
      
        self.ignored_forums = {
          1329352004224680040, # manager forum
          1109026283331014677, # staff forum
        }

        # Cooldown duration in seconds
        self.cooldown_seconds = 60
        self.last_executed = {}


    @commands.Cog.listener()
    async def on_message(self, message) :
        """Checks messages in the review channel and enforces format."""
        if message.author.bot :
            return

        # Ignore normal channels
        if isinstance(message.channel, TextChannel):
            if message.channel.id in self.ignored_channels:
                return
        # Ignore threads inside forums
        if isinstance(message.channel, Thread):
            if message.channel.parent and message.channel.parent.id in self.ignored_forums:
                return
            
        if "daken" not in message.content.lower():
            return

        channel_id = message.channel.id

        # cooldown check
        now = time.time()
        last_time = self.last_executed.get(channel_id, 0)
        if now - last_time < self.cooldown_seconds:
            return  # still in cooldown

        await message.reply(embed=self.akihiro_message)

        # update last time used
        self.last_executed[channel_id] = now
        
async def setup(bot: commands.Bot) :
    """Standard setup function for discord.py cogs."""
    await bot.add_cog(AkihiroCog(bot))
