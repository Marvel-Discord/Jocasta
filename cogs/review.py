from discord.ext import commands
from discord import Embed, Forbidden
import config
import re


class ReviewCog(commands.Cog) :
    def __init__(self, bot) :
        self.bot = bot
    
        self.review_channel_id = config.comic_review_channel

        self.review_instruction_embed = Embed(
            title="**How to Post Reviews**",
            description=(
                "Please follow the format below when writing your review.\n"
                "Your message will be deleted if it doesn't follow the format.\n\n"
                "**Notes:**\n"
                "- Only post reviews for full runs, collected editions, or one-shots.\n"
                "- No individual issue reviews (unless it's a one-shot)."
                "- As these reviews are meant for people who haven't read the comic yet, please use spoiler brackets ``||like this||`` if you want to include spoilers in your review. Not using spoiler brackets on spoilers may lead to your review being removed."
            ),
        )

        self.format_message = (
            "```\n"
            "## Comic Name\n"
            "**Year and writer:**\n"
            "**Rating:** x/10\n"
            "**Review:** A few words about your thoughts on the comic and why you gave it that rating. You could include details such as the length of the book, quality of the art, required background reading, etc. Make sure to use spoiler brackets ||like this|| for any spoilers you want to include.\n"
            "```"
        )

    @commands.Cog.listener()
    async def on_message(self, message) :
        """Checks messages in the review channel and enforces format."""
        if message.author.bot :
            return
        
        if message.channel.id != self.review_channel_id :
            return
        
        # Regex pattern to match section headers (## or bold headers)
        pattern = re.compile(
            r"##\s*.+\s*"                                   # Comic name header
            r"\*\*year and writer:\*\*.+?"
            r"\*\*rating:\*\*.+?"
            r"\*\*review:\*\*.+",
            re.IGNORECASE | re.DOTALL
        )

        if not pattern.search(message.content):

            try:
                # Try to DM the user before deleting the message
                reason = (
                    "Your review post was removed because it doesn't follow the required format.\n"
                    "Please make sure to follow the provided format.\n"
                    "If you keep experiencing issues, try copying the format or a previous review, and fill in your own information.\n\n"
                    "Here’s what you wrote so you can easily copy and fix it:"
                )
        
                await message.author.send(
                    f"Hey {message.author.display_name},\n\n{reason}\n"
                    f"```\n{message.content[:1900]}\n```"
                )
            except Forbidden:
                # User has DMs disabled or blocked the bot
                pass
            
            await message.delete()
            return
        
        # Remove previous embed messages from bot to keep latest at bottom
        async for msg in message.channel.history(limit = 5) :
            if msg.author == self.bot.user :
                await msg.delete()
            
        # Send sticky embeds at bottom
        await message.channel.send(embed=self.review_instruction_embed)
        await message.channel.send(content=self.format_message)

        # Add reaction to passed messages
        emoji = self.bot.get_emoji(config.review_reaction_emoji) 
        await message.add_reaction(emoji)

        # Create a thread for discussion
        first_line = message.content.strip().split("\n", 1)[0]
        comic_name = first_line.replace("##", "").strip()

        thread = await message.create_thread(
            name=f"Review: {comic_name} by {message.author.display_name}",
            auto_archive_duration=4320  # 3 days
        )

        await thread.send(
            f"Thread for discussing **{comic_name}**, reviewed by {message.author.display_name}!"
        )
            
async def setup(bot: commands.Bot) :
    """Standard setup function for discord.py cogs."""
    await bot.add_cog(ReviewCog(bot))
