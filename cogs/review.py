from discord.ext import commands
from discord import Embed


class ReviewCog(commands.Cog) :
    def __init__(self, bot) :
        self.bot = bot
    
        self.review_channel_id = 1382732564610945194 

        # Sticky message
        self.review_format_embed = (
            Embed(
                title = "**Review Format**",
                description = (
                    "Use the following template to post.\n"
                    "```Comic Name\n"
                    "**Rating:** x/10\n"
                    "**Length:** x issues or x pages or something similar\n"
                    "**Review:** A few words about your thoughts on the comic and why you gave it that rating```"
                    ),
                )
            .add_field(
                name = "**Please follow the above template.**",
                value = "Your message will be removed if it doesn't match the format.\n\nPlease **only** write reviews for full runs/events/collected editions/stories, and not for individual issues (unless the individual issue in question is a one-shot).",
                inline = False,
                )
            )

    @commands.Cog.listener()
    async def on_message(self, message) :
        """Checks messages in the review channel and enforces format."""
        if message.author.bot :
            return
        
        if message.channel.id != self.review_channel_id :
            return
        
        # Check for required keywords
        required_keywords = ["rating", "length", "review"]
        if not all(keyword in message.content.lower() for keyword in required_keywords) :
            await message.delete()
            return
        
        # Remove previous embed messages from bot to keep latest at bottom
        async for msg in message.channel.history(limit = 3) :
            if msg.author == self.bot.user :
                await msg.delete()
            
        # Send new embed to appear at bottom
        await message.channel.send(embed = self.review_format_embed)
            
            
async def setup(bot: commands.Bot) :
    """Standard setup function for discord.py cogs."""
    await bot.add_cog(ReviewCog(bot))
