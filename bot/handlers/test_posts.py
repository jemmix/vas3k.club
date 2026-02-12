"""Tests for bot/handlers/posts.py handlers."""

from asgiref.sync import sync_to_async
from unittest.mock import patch

from django.test import TestCase

from bot.handlers.posts import subscribe, unsubscribe
from bot.test_helpers import (
    create_test_user,
    create_callback_query_update,
    ANSWER_CALLBACK_QUERY_RESPONSE,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post
from posts.models.subscriptions import PostSubscription


class SubscribeTest(BaseTelegramTest, TestCase):
    """Test the subscribe handler"""

    tags = {"telegram", "telegram_bot"}

    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            slug="test-post",
            title="Test Post",
            text="Test content",
        )
        self.close_db_patch = patch("bot.handlers.common.close_old_connections")
        self.close_db_patch.start()

    def tearDown(self):
        super().tearDown()
        PostSubscription.objects.filter(post=self.post).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()
        self.close_db_patch.stop()

    async def test_subscribes_user_to_post(self):
        """Should subscribe user to post"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"subscribe:{self.post.id}",
        )
        context = None

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": f"Вы подписались на уведомления о новых комментариях к посту «{self.post.title}» 🔔",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await subscribe(update, context)

        # Verify subscription was created
        subscription = await PostSubscription.objects.filter(user=self.user, post=self.post).afirst()
        self.assertIsNotNone(subscription)


class UnsubscribeTest(BaseTelegramTest, TestCase):
    """Test the unsubscribe handler"""

    tags = {"telegram", "telegram_bot"}

    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            slug="test-post",
            title="Test Post",
            text="Test content",
        )
        self.close_db_patch = patch("bot.handlers.common.close_old_connections")
        self.close_db_patch.start()

    def tearDown(self):
        super().tearDown()
        PostSubscription.objects.filter(post=self.post).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()
        self.close_db_patch.stop()

    async def test_unsubscribes_user_from_post(self):
        """Should unsubscribe user from post"""
        # Create subscription first
        await sync_to_async(PostSubscription.subscribe)(
            user=self.user,
            post=self.post,
            type=PostSubscription.TYPE_TOP_LEVEL_ONLY,
        )

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"unsubscribe:{self.post.id}",
        )
        context = None

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": f"Вы отписались от комментариев к посту «{self.post.title}» 🔕",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await unsubscribe(update, context)

        # Verify subscription was deleted
        subscription = await PostSubscription.objects.filter(user=self.user, post=self.post).afirst()
        self.assertIsNone(subscription)

    async def test_handles_already_unsubscribed(self):
        """Should handle when user wasn't subscribed"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"unsubscribe:{self.post.id}",
        )
        context = None

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "Вы и не были подписаны на уведомления к этому посту ❌",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await unsubscribe(update, context)
