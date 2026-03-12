import pytest

from bot.database import (
    add_subscription,
    get_all_subscriptions,
    get_episode_summary,
    get_episode_transcript,
    get_or_create_user,
    get_subscription_by_id,
    get_subscriptions,
    is_episode_seen,
    mark_episode_seen,
    remove_subscription,
    remove_subscription_by_id,
    set_subscription_prompt,
)


async def _make_user(telegram_user_id=12345, chat_id=99999):
    return await get_or_create_user(telegram_user_id, chat_id)


class TestGetOrCreateUser:
    async def test_returns_ulid_string(self, tmp_db):
        uid = await _make_user()
        assert isinstance(uid, str)
        assert len(uid) > 0

    async def test_same_telegram_id_returns_same_uid(self, tmp_db):
        uid1 = await get_or_create_user(111, 999)
        uid2 = await get_or_create_user(111, 999)
        assert uid1 == uid2

    async def test_different_telegram_ids_return_different_uids(self, tmp_db):
        uid1 = await get_or_create_user(111, 999)
        uid2 = await get_or_create_user(222, 999)
        assert uid1 != uid2


class TestAddAndGetSubscriptions:
    async def test_add_and_retrieve(self, tmp_db):
        uid = await _make_user()
        await add_subscription(uid, "My Show", "http://example.com/feed.rss")
        subs = await get_subscriptions(uid)
        assert len(subs) == 1
        assert subs[0].podcast_title == "My Show"
        assert subs[0].rss_url == "http://example.com/feed.rss"
        assert subs[0].custom_prompt is None

    async def test_user_with_no_subs_returns_empty(self, tmp_db):
        uid = await _make_user()
        subs = await get_subscriptions(uid)
        assert subs == []

    async def test_two_subs_both_returned(self, tmp_db):
        uid = await _make_user()
        await add_subscription(uid, "Show A", "http://a.com/feed.rss")
        await add_subscription(uid, "Show B", "http://b.com/feed.rss")
        subs = await get_subscriptions(uid)
        assert len(subs) == 2
        titles = {s.podcast_title for s in subs}
        assert titles == {"Show A", "Show B"}


class TestGetAllSubscriptions:
    async def test_returns_subscription_with_chat(self, tmp_db):
        uid = await get_or_create_user(12345, 67890)
        await add_subscription(uid, "My Show", "http://example.com/feed.rss")
        all_subs = await get_all_subscriptions()
        assert len(all_subs) == 1
        assert all_subs[0].chat_id == 67890
        assert all_subs[0].podcast_title == "My Show"

    async def test_no_data_returns_empty(self, tmp_db):
        all_subs = await get_all_subscriptions()
        assert all_subs == []


class TestRemoveSubscription:
    async def test_partial_title_match_removed(self, tmp_db):
        uid = await _make_user()
        await add_subscription(uid, "My Podcast Show", "http://example.com/feed.rss")
        result = await remove_subscription(uid, "Podcast")
        assert result is True
        subs = await get_subscriptions(uid)
        assert subs == []

    async def test_no_match_returns_false(self, tmp_db):
        uid = await _make_user()
        result = await remove_subscription(uid, "Nonexistent")
        assert result is False

    async def test_case_insensitive(self, tmp_db):
        uid = await _make_user()
        await add_subscription(uid, "My Show", "http://example.com/feed.rss")
        result = await remove_subscription(uid, "SHOW")
        assert result is True


class TestRemoveSubscriptionById:
    async def test_sub_gone_after_removal(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "My Show", "http://example.com/feed.rss")
        await remove_subscription_by_id(sub_id)
        sub = await get_subscription_by_id(sub_id)
        assert sub is None

    async def test_unknown_id_is_noop(self, tmp_db):
        await remove_subscription_by_id("nonexistent-id")  # should not raise


class TestGetSubscriptionById:
    async def test_returns_correct_fields(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "My Show", "http://example.com/feed.rss")
        sub = await get_subscription_by_id(sub_id)
        assert sub is not None
        assert sub.id == sub_id
        assert sub.podcast_title == "My Show"
        assert sub.rss_url == "http://example.com/feed.rss"

    async def test_unknown_id_returns_none(self, tmp_db):
        sub = await get_subscription_by_id("does-not-exist")
        assert sub is None


class TestEpisodeSeen:
    async def test_false_before_marking(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        result = await is_episode_seen(sub_id, "guid123")
        assert result is False

    async def test_true_after_marking(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123")
        result = await is_episode_seen(sub_id, "guid123")
        assert result is True

    async def test_mark_twice_no_exception(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123", summary="first")
        await mark_episode_seen(sub_id, "guid123", summary="second")  # ON CONFLICT DO UPDATE

    async def test_second_call_with_summary_updates(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123", summary=None)
        await mark_episode_seen(sub_id, "guid123", summary="updated summary")
        transcript = await get_episode_transcript(sub_id, "guid123")
        # summary updated; transcript still None
        assert transcript is None


class TestGetEpisodeTranscript:
    async def test_returns_stored_transcript(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123", transcript="full transcript text")
        result = await get_episode_transcript(sub_id, "guid123")
        assert result == "full transcript text"

    async def test_unknown_guid_returns_none(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        result = await get_episode_transcript(sub_id, "no-such-guid")
        assert result is None


class TestGetEpisodeSummary:
    async def test_returns_stored_summary(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123", summary="great episode")
        result = await get_episode_summary(sub_id, "guid123")
        assert result == "great episode"

    async def test_unknown_guid_returns_none(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        result = await get_episode_summary(sub_id, "no-such-guid")
        assert result is None

    async def test_no_summary_returns_none(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await mark_episode_seen(sub_id, "guid123", transcript="some transcript")
        result = await get_episode_summary(sub_id, "guid123")
        assert result is None


class TestSetSubscriptionPrompt:
    async def test_updates_custom_prompt(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await set_subscription_prompt(sub_id, "Summarize briefly")
        sub = await get_subscription_by_id(sub_id)
        assert sub.custom_prompt == "Summarize briefly"

    async def test_can_set_to_none(self, tmp_db):
        uid = await _make_user()
        sub_id = await add_subscription(uid, "Show", "http://example.com/feed.rss")
        await set_subscription_prompt(sub_id, "Some prompt")
        await set_subscription_prompt(sub_id, None)
        sub = await get_subscription_by_id(sub_id)
        assert sub.custom_prompt is None
