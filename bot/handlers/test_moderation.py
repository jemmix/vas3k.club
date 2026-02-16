"""Tests for bot/handlers/moderation.py handlers."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from telegram.ext import CallbackContext

from django.test import TestCase, override_settings

from bot.handlers.common import UserRejectReason, PostRejectReason
from bot.handlers.moderation import (
    approve_post,
    forgive_post,
    reject_post,
    approve_user_profile,
    reject_user_profile,
)
from bot.test_helpers import (
    create_test_user,
    create_callback_query_update,
    EDIT_MESSAGE_REPLY_MARKUP_RESPONSE,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post
from posts.models.subscriptions import PostSubscription
from users.models.user import User


class ApprovePostTest(BaseTelegramTest, TestCase):
    """Test the approve_post handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    EDIT_MESSAGE_REPLY_MARKUP_PATH = f"/{BaseTelegramTest.TOKEN}/editMessageReplyMarkup"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            roles=[User.ROLE_MODERATOR],
        )
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
            moderation_status=Post.MODERATION_PENDING,
            visibility=Post.VISIBILITY_LINK_ONLY,
        )

        # Mock notification functions
        self.notify_post_approved_patch = patch("bot.handlers.moderation.notify_post_approved")
        self.announce_in_club_chats_patch = patch("bot.handlers.moderation.announce_in_club_chats")
        self.notify_collectible_patch = patch("bot.handlers.moderation.async_task")
        self.update_search_index_patch = patch("bot.handlers.moderation.SearchIndex.update_post_index")

        self.notify_post_approved_patch.start()
        self.announce_in_club_chats_patch.start()
        self.notify_collectible_patch.start()
        self.update_search_index_patch.start()

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.moderator.delete()
        self.notify_post_approved_patch.stop()
        self.announce_in_club_chats_patch.stop()
        self.notify_collectible_patch.stop()
        self.update_search_index_patch.stop()

    @override_settings(APP_HOST="https://vas3k.club", TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_approves_post(self):
        """Should approve post and send confirmation"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"approve_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"👍 Пост «{self.post.title}» одобрен (Test): https://vas3k.club/post/{self.post.slug}/",
                        "link_preview_options": "{\"is_disabled\": true}",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await approve_post(update, context)

        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_APPROVED)
        self.assertEqual(self.post.visibility, Post.VISIBILITY_EVERYWHERE)
        self.assertIsNotNone(self.post.published_at)

    @override_settings(APP_HOST="https://vas3k.club", TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_approves_room_only_post(self):
        """Should approve room-only post with different message"""
        from rooms.models import Room

        room = await Room.objects.acreate(
            title="Test Room",
            slug="test-room",
        )

        self.post.room = room
        self.post.is_room_only = True
        await self.post.asave()

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"approve_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"😎 Пост «{self.post.title}» хорош для комнаты «{room.title}», но не будет отображаться на главной (Test): https://vas3k.club/post/{self.post.slug}/",
                        "link_preview_options": "{\"is_disabled\": true}",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await approve_post(update, context)

        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_APPROVED)

        await room.adelete()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_already_moderated_post(self):
        """Should reject post that was already moderated"""
        self.post.moderation_status = Post.MODERATION_APPROVED
        await self.post.asave()

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"approve_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"Пост «{self.post.title}» уже был отмодерирован ранее: {Post.MODERATION_APPROVED}",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await approve_post(update, context)

        # Should not change status
        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_APPROVED)


class ForgivePostTest(BaseTelegramTest, TestCase):
    """Test the forgive_post handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    EDIT_MESSAGE_REPLY_MARKUP_PATH = f"/{BaseTelegramTest.TOKEN}/editMessageReplyMarkup"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            roles=[User.ROLE_MODERATOR],
        )
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
            moderation_status=Post.MODERATION_PENDING,
            visibility=Post.VISIBILITY_LINK_ONLY,
            collectible_tag_code="TEST_TAG",
        )

        self.update_search_index_patch = patch("bot.handlers.moderation.SearchIndex.update_post_index")

        self.update_search_index_patch.start()

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.moderator.delete()
        self.update_search_index_patch.stop()

    @override_settings(APP_HOST="https://vas3k.club", TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_forgives_post(self):
        """Should forgive post and remove collectible tag"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"forgive_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"😕 Пост «{self.post.title}» не одобрен, но оставлен на сайте (Test): https://vas3k.club/post/{self.post.slug}/",
                        "link_preview_options": "{\"is_disabled\": true}",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await forgive_post(update, context)

        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_FORGIVEN)
        self.assertEqual(self.post.visibility, Post.VISIBILITY_EVERYWHERE)
        self.assertIsNone(self.post.collectible_tag_code)


class RejectPostTest(BaseTelegramTest, TestCase):
    """Test the reject_post handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    EDIT_MESSAGE_REPLY_MARKUP_PATH = f"/{BaseTelegramTest.TOKEN}/editMessageReplyMarkup"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            roles=[User.ROLE_MODERATOR],
        )
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
            moderation_status=Post.MODERATION_PENDING,
            visibility=Post.VISIBILITY_LINK_ONLY,
        )

        self.notify_post_rejected_patch = patch("bot.handlers.moderation.notify_post_rejected")
        self.update_search_index_patch = patch("bot.handlers.moderation.SearchIndex.update_post_index")

        self.notify_post_rejected_patch.start()
        self.update_search_index_patch.start()

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.moderator.delete()
        self.notify_post_rejected_patch.stop()
        self.update_search_index_patch.stop()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_post_with_default_reason(self):
        """Should reject post with default reason"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"reject_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"👎 Пост «{self.post.title}» перенесен в черновики по причине «{PostRejectReason.draft.value}» (Test)",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await reject_post(update, context)

        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_REJECTED)
        self.assertEqual(self.post.visibility, Post.VISIBILITY_DRAFT)

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_post_with_specific_reason(self):
        """Should reject post with specific reason"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"reject_post_title:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"👎 Пост «{self.post.title}» перенесен в черновики по причине «{PostRejectReason.title.value}» (Test)",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await reject_post(update, context)

        await self.post.arefresh_from_db()
        self.assertEqual(self.post.moderation_status, Post.MODERATION_REJECTED)


class ApproveUserProfileTest(BaseTelegramTest, TestCase):
    """Test the approve_user_profile handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    EDIT_MESSAGE_REPLY_MARKUP_PATH = f"/{BaseTelegramTest.TOKEN}/editMessageReplyMarkup"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            roles=[User.ROLE_MODERATOR],
        )
        self.user = create_test_user(
            moderation_status=User.MODERATION_STATUS_ON_REVIEW,
        )
        self.intro = Post.objects.create(
            author=self.user,
            type=Post.TYPE_INTRO,
            slug=f"intro-{self.user.slug}",
            title=f"#intro от @{self.user.slug}",
            text="Test intro",
            moderation_status=Post.MODERATION_PENDING,
            visibility=Post.VISIBILITY_DRAFT,
        )

        # Mock notification functions
        self.notify_user_approved_patch = patch("bot.handlers.moderation.notify_user_profile_approved")
        self.send_welcome_drink_patch = patch("bot.handlers.moderation.send_welcome_drink")
        self.announce_in_club_chats_patch = patch("bot.handlers.moderation.announce_in_club_chats")
        self.update_search_index_patch = patch("bot.handlers.moderation.SearchIndex.update_user_index")

        self.notify_user_approved_patch.start()
        self.send_welcome_drink_patch.start()
        self.announce_in_club_chats_patch.start()
        self.update_search_index_patch.start()

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(id=self.intro.id).delete()
        self.user.delete()
        self.moderator.delete()
        self.notify_user_approved_patch.stop()
        self.send_welcome_drink_patch.stop()
        self.announce_in_club_chats_patch.stop()
        self.update_search_index_patch.stop()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_approves_user_profile(self):
        """Should approve user and intro"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"approve_user:{self.user.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"✅ Пользователь «{self.user.full_name}» одобрен (Test)",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await approve_user_profile(update, context)

        await self.user.arefresh_from_db()
        await self.intro.arefresh_from_db()

        self.assertEqual(self.user.moderation_status, User.MODERATION_STATUS_APPROVED)
        self.assertEqual(self.intro.moderation_status, Post.MODERATION_APPROVED)
        self.assertEqual(self.intro.visibility, Post.VISIBILITY_EVERYWHERE)

        # Check subscription was created
        subscription = await PostSubscription.objects.filter(
            user=self.user,
            post=self.intro,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        ).afirst()
        self.assertIsNotNone(subscription)

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_already_approved_user(self):
        """Should reject if user already approved"""
        self.user.moderation_status = User.MODERATION_STATUS_APPROVED
        await self.user.asave()

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"approve_user:{self.user.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"Пользователь «{self.user.full_name}» уже одобрен",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await approve_user_profile(update, context)


class RejectUserProfileTest(BaseTelegramTest, TestCase):
    """Test the reject_user_profile handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    EDIT_MESSAGE_REPLY_MARKUP_PATH = f"/{BaseTelegramTest.TOKEN}/editMessageReplyMarkup"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            roles=[User.ROLE_MODERATOR],
        )
        self.user = create_test_user(
            moderation_status=User.MODERATION_STATUS_ON_REVIEW,
        )

        # Mock notification functions
        self.notify_user_rejected_patch = patch("bot.handlers.moderation.notify_user_profile_rejected")
        self.send_user_rejected_email_patch = patch("bot.handlers.moderation.send_user_rejected_email")

        self.notify_user_rejected_patch.start()
        self.send_user_rejected_email_patch.start()

    def tearDown(self):
        super().tearDown()
        self.user.delete()
        self.moderator.delete()
        self.notify_user_rejected_patch.stop()
        self.send_user_rejected_email_patch.stop()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_user_with_default_reason(self):
        """Should reject user with default reason"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"reject_user:{self.user.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"❌ Пользователь «{self.user.full_name}» отклонен по причине «{UserRejectReason.intro.value}» (Test)",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await reject_user_profile(update, context)

        await self.user.arefresh_from_db()
        self.assertEqual(self.user.moderation_status, User.MODERATION_STATUS_REJECTED)

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_user_with_specific_reason(self):
        """Should reject user with specific reason"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"reject_user_ai:{self.user.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"❌ Пользователь «{self.user.full_name}» отклонен по причине «{UserRejectReason.ai.value}» (Test)",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await reject_user_profile(update, context)

        await self.user.arefresh_from_db()
        self.assertEqual(self.user.moderation_status, User.MODERATION_STATUS_REJECTED)

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_already_rejected_user(self):
        """Should reject if user already rejected"""
        self.user.moderation_status = User.MODERATION_STATUS_REJECTED
        await self.user.asave()

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"reject_user:{self.user.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"Пользователь «{self.user.full_name}» уже был отклонен и пошел все переделывать",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.EDIT_MESSAGE_REPLY_MARKUP_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "100",
                    },
                ),
                EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(),
            ),
        ])

        await reject_user_profile(update, context)

        # Should remain rejected
        await self.user.arefresh_from_db()
        self.assertEqual(self.user.moderation_status, User.MODERATION_STATUS_REJECTED)
