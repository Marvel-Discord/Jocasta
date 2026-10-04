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
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
polls_api_base_url = os.getenv("POLLS_API_BASE_URL", "http://localhost:8000/api/v1")
polls_api_token = os.getenv("POLLS_API_TOKEN", "")
global_slashies = os.getenv("GLOBAL_SLASHIES", "False").lower() == "true"
guild_ids = [
    int(x) for x in os.getenv("GUILD_IDS", "288896937074360321,1010550869391065169").split(",") if x
]
database_listener_logs = os.getenv("DATABASE_LISTENER_LOGS", "True").lower() == "true"

homeserver = int(os.getenv("HOMESERVER"))
newschannels = [int(x) for x in os.getenv("NEWSCHANNELS", "").split(",") if x]
newspingrole = int(os.getenv("NEWSPINGROLE"))
newspingbuffertime = int(os.getenv("NEWSPINGBUFFERTIME", 600))
spoiler_thread_channel = int(os.getenv("SPOILER_THREAD_CHANNEL"))
request_spoiler_thread_channel = int(os.getenv("REQUEST_SPOILER_THREAD_CHANNEL"))

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
