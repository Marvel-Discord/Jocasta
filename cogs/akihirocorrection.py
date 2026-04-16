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
                "\"Daken\" is a derogatory slur used against people who aren't fully Japanese. While you may not be familiar with this word's origin, it is often considered disrespectful and offensive.\n\n"
                "The character, Daken, has numerous other names that Marvel comics prefer to use today, including his given name, **Akihiro**, and \"superhero names\" **Dark Wolverine**, **Hellverine**, and **Fang**.\n\n"
                "We encourage you and the whole Marvel community to use these names instead of \"Daken\"."
            ),
        )

        # Manual overrides for blocking/allowing channels
        self.blocked_channels = {}
        self.allowed_channels = {
            1382732564610945194, # comic review corner
            1362621880779014397, # bookclub organising (thread)
            1109726292208779385, # tykhe rolling
            1110217807116906507, # tykhe rolling 2
            1111142854186762271, # tykhe roll nft
            1109727103722729573, # tykhe commands
            1110217858446790656, # tykhe commands 2
            1111141979376582729, # tykhe trade board
            1109727127051440148, # tykhe discussion
        }

        # Manual overrides for blocking/allowing threads from parent channels/forums 
        # Note that if you only allow/block a channel in the above lists, any created threads within that channel will still behave following normal rules
        self.blocked_parents = {}
        self.allowed_parents = {
            1382732564610945194, # comic review corner
        }

        # Cooldown duration in seconds
        self.cooldown_seconds = 60
        self.last_executed = {}

    def everyone_can_talk(self, ch, everyone_role):
        permissions = ch.permissions_for(everyone_role)
        
        return (permissions.send_messages is not False)
    
    def is_blocked_channel(self, channel):
        guild = channel.guild
    
        # Manual allowlist
        if channel.id in self.allowed_channels:
            return False
        if isinstance(channel, Thread) and channel.parent and channel.parent.id in self.allowed_parents:
            return False
    
        # Manual blocklist
        if channel.id in self.blocked_channels:
            return True
        if isinstance(channel, Thread) and channel.parent and channel.parent.id in self.blocked_parents:
            return True
        
        # @everyone permission check
        everyone_role = guild.default_role
        
        if isinstance(channel, Thread):
            parent = channel.parent
            if parent and self.everyone_can_talk(parent, everyone_role):
                return True
        else:
            if self.everyone_can_talk(channel, everyone_role):
                return True
    
        return False
    
    @commands.Cog.listener()
    async def on_message(self, message) :
        
        pattern = re.compile(
            r"(.*daken.*)",
            re.IGNORECASE
        )
        
        if not pattern.search(message.content):
            return

        if message.author.bot :
            return

        # Ignore allowed channels
        if not self.is_blocked_channel(message.channel):
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
