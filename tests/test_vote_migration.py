"""Tests for the vote write-path migration from postgres to the polls API."""
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
from funcs.polls_api import PollsAPIError
from funcs.polls_api_models import UserVote, VoteCounts


def make_cog():
    class FakeBot:
        def __init__(self):
            self.tasks = {}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()

    return PollsCog(FakeBot())


def make_poll(**overrides):
    poll = {
        "id": 42,
        "question": "Best hero?",
        "active": True,
        "persistent": False,
        "published": True,
        "choices": ["A", "B", "C"],
        "votes": [0, 0, 0],
        "total_votes": 0,
        "show_question": True,
        "show_options": True,
        "show_voting": True,
        "thread_question": None,
    }
    poll.update(overrides)
    return poll


def make_user(user_id=1234):
    user = MagicMock()
    user.id = user_id
    return user


def make_counts():
    return VoteCounts(votes=[1, 2, 0], total_votes=3)


async def test_vote_calls_cast_vote_with_poll_user_and_choice():
    cog = make_cog()
    cog.bot.polls_api.cast_vote = AsyncMock(return_value=make_counts())
    cog.updatepollmessage = AsyncMock()

    result = await cog.cast_vote(make_poll(), make_user(1234), 1)

    cog.bot.polls_api.cast_vote.assert_awaited_once_with(42, 1234, 1)
    assert result == 1


async def test_vote_clear_sentinel_maps_to_none_for_api_delete():
    cog = make_cog()
    cog.bot.polls_api.cast_vote = AsyncMock(return_value=make_counts())
    cog.updatepollmessage = AsyncMock()

    result = await cog.cast_vote(make_poll(), make_user(1234), -1)

    cog.bot.polls_api.cast_vote.assert_awaited_once_with(42, 1234, None)
    assert result == -1


async def test_vote_updates_poll_from_vote_counts_and_rerenders():
    cog = make_cog()
    cog.bot.polls_api.cast_vote = AsyncMock(return_value=make_counts())
    cog.updatepollmessage = AsyncMock()

    result = await cog.cast_vote(make_poll(), make_user(1234), 0)

    cog.updatepollmessage.assert_awaited_once()
    rendered = cog.updatepollmessage.await_args.args[0]
    assert rendered["votes"] == [1, 2, 0]
    assert rendered["total_votes"] == 3
    assert result == 0


async def test_vote_api_error_propagates_without_rerender():
    cog = make_cog()
    cog.bot.polls_api.cast_vote = AsyncMock(side_effect=PollsAPIError(503, "down"))
    cog.updatepollmessage = AsyncMock()

    try:
        await cog.cast_vote(make_poll(), make_user(1234), 1)
    except PollsAPIError:
        pass
    else:
        raise AssertionError("PollsAPIError should propagate to the view callback")

    cog.updatepollmessage.assert_not_awaited()


def make_interaction(user_id=1234):
    interaction = MagicMock()
    interaction.user = make_user(user_id)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def test_view_vote_error_sends_ephemeral_error_reply():
    cog = make_cog()
    poll = make_poll()
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.cast_vote = AsyncMock(side_effect=PollsAPIError(0, "network error"))
    cog.add_to_thread = AsyncMock()

    view = PollsCog.PollView(cog, poll, active=True)
    interaction = make_interaction()
    await view.vote(cog, poll, interaction, 1)

    interaction.followup.send.assert_awaited_once_with(
        "Something went wrong, please try again", ephemeral=True
    )
    cog.add_to_thread.assert_not_awaited()


async def test_view_vote_success_sends_confirmation():
    cog = make_cog()
    poll = make_poll()
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.cast_vote = AsyncMock(return_value=1)
    cog.add_to_thread = AsyncMock()

    view = PollsCog.PollView(cog, poll, active=True)
    interaction = make_interaction()
    await view.vote(cog, poll, interaction, 1)

    cog.cast_vote.assert_awaited_once_with(poll, interaction.user, 1)
    interaction.followup.send.assert_awaited_once()
    assert "you voted" in interaction.followup.send.await_args.args[0]
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True
    cog.add_to_thread.assert_awaited_once()


async def test_get_user_vote_returns_matching_choice():
    cog = make_cog()
    cog.bot.polls_api.get_user_votes = AsyncMock(
        return_value=[
            UserVote(id=1, user_id=1234, poll_id=41, choice=0),
            UserVote(id=2, user_id=1234, poll_id=42, choice=2),
        ]
    )

    assert await cog.get_user_vote(make_poll(), make_user(1234)) == 2
    cog.bot.polls_api.get_user_votes.assert_awaited_once_with(1234)


async def test_get_user_vote_returns_none_when_absent():
    cog = make_cog()
    cog.bot.polls_api.get_user_votes = AsyncMock(return_value=[])

    assert await cog.get_user_vote(make_poll(), make_user(1234)) is None
