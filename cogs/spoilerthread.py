from discord.ext import commands
from discord import Embed
import config

class SpoilerThreadCog(commands.Cog) :
    def __init__(self, bot) :
        self.bot = bot
    
        self.request_spoiler_thread_id = config.spoiler_thread_channel
    
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


            
async def setup(bot: commands.Bot) :
    await bot.add_cog(SpoilerThreadCog(bot))
