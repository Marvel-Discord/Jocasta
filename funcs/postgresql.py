from discord.ext import commands
import asyncpg

from config import *


async def init_db_connection(conn):
    await conn.execute("SET application_name = 'bot'")


class PostgreSQLCog(commands.Cog, name="PostgreSQL"):
    """Loads PostgreSQL"""

    def __init__(self, bot):
        self.bot = bot

        self.credentials = postgres_credentials
        self.bot.loop.create_task(self.loadPostgreSQL())

        self.bot.postgresql_loaded = False

    async def loadPostgreSQL(self):
        self.bot.db = await asyncpg.create_pool(
            **self.credentials, init=init_db_connection
        )
        self.bot.postgresql_loaded = True

        create_functions = [
            """
                create function commuted_regexp_match(text,text) returns bool as
                'select $2 ~* $1;'
                language sql;
            """,
            """
                create operator ~! (
                     procedure=commuted_regexp_match(text,text),
                     leftarg=text, rightarg=text
                );
            """,
        ]

        for f in create_functions:
            try:
                await self.bot.db.execute(f)
            except asyncpg.exceptions.DuplicateFunctionError:
                pass


async def setup(bot):
    await bot.add_cog(PostgreSQLCog(bot))
