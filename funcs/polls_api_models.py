from datetime import datetime

from pydantic import BaseModel


class Poll(BaseModel):
    id: int
    question: str
    published: bool
    active: bool
    guild_id: int
    choices: list[str]
    votes: list[int]
    total_votes: int
    time: datetime | None
    start_time: datetime | None
    end_time: datetime | None
    num: int | None
    message_id: int | None
    crosspost_message_ids: list[int]
    tag: int
    image: str | None
    description: str | None
    thread_question: str | None
    show_question: bool
    show_options: bool
    show_voting: bool
    fallback: bool


class Tag(BaseModel):
    tag: int
    name: str
    guild_id: int
    channel_id: int
    crosspost_channels: list[int]
    crosspost_servers: list[int]
    current_num: int | None
    colour: int | None
    end_message: str | None
    end_message_latest_ids: list[int]
    end_message_replace: bool
    end_message_role_ids: list[int]
    end_message_ping: bool
    end_message_self_assign: bool
    persistent: bool


class GuildSettings(BaseModel):
    guild_id: int
    default_channel_id: int
    manage_channel_id: list[int]
    manager_role_id: list[int]
    default_colour: int | None
    fallback_channel_id: int | None


class VoteCounts(BaseModel):
    votes: list[int]
    total_votes: int


class UserVote(BaseModel):
    id: int
    user_id: int
    poll_id: int
    choice: int


class PollListResponse(BaseModel):
    data: list[Poll]
    meta: dict


class BotEventFrame(BaseModel):
    table: str
    operation: str
    id: int
