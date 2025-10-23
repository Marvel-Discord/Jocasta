import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
BOT_PREFIX = os.getenv("BOT_PREFIX", "~")

postgres_credentials = {
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
    "database": os.getenv("POSTGRES_DATABASE"),
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
}
global_slashies = os.getenv("GLOBAL_SLASHIES", "False").lower() == "true"
database_listener_logs = os.getenv("DATABASE_LISTENER_LOGS", "True").lower() == "true"

homeserver = int(os.getenv("HOMESERVER"))
newschannels = [int(x) for x in os.getenv("NEWSCHANNELS", "").split(",") if x]
newspingrole = int(os.getenv("NEWSPINGROLE"))
newspingbuffertime = int(os.getenv("NEWSPINGBUFFERTIME", 600))
spoiler_thread_channel = int(os.getenv("SPOILER_THREAD_CHANNEL"))

raidlogservers = {
    int(k): int(v, 16)
    for pair in os.getenv("RAIDLOGSERVERS", "").split(",")
    if pair
    for k, v in [pair.split(":")]
}
raidlogdest = [int(x) for x in os.getenv("RAIDLOGDEST", "").split(",") if x]

TMDB_KEY = os.getenv("TMDB_KEY")
GITHUB_PAT_DOCS = os.getenv("GITHUB_PAT_DOCS")

comic_review_channel = int(os.getenv("COMIC_REVIEW_CHANNEL", 0))
review_reaction_emoji = int(os.getenv("REVIEW_REACTION_EMOJI", 0))
