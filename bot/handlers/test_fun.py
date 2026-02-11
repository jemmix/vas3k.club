"""Tests for bot/handlers/fun.py handlers."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from telegram.ext import CallbackContext

from django.test import TestCase

from bot.handlers.fun import command_horo, command_random
from bot.test_helpers import (
    create_test_user,
    create_command_update,
    SEND_MESSAGE_RESPONSE,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post


class CommandHoroTest(BaseTelegramTest, TestCase):
    """Test the command_horo handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")

    def tearDown(self):
        super().tearDown()
        self.user.delete()

    @patch("bot.handlers.fun.parse_horoscope")
    async def test_sends_horoscope(self, mock_parse):
        """Should send horoscope message"""
        mock_parse.return_value = {
            "club_day": 42,
            "phase_sign": "🌕",
            "phase_description": "Test phase description",
        }

        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/horo",
        )
        context = MagicMock(spec=CallbackContext)

        expected_text = "Сегодня 42 день от сотворения Клуба, 🌕\n\nTest phase description"

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": expected_text,
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_horo(update, context)

        # Verify parse_horoscope was called
        mock_parse.assert_called_once()


class CommandRandomTest(BaseTelegramTest, TestCase):
    """Test the command_random handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")

        # Create a test post
        now = datetime.now(timezone.utc)
        self.post = Post.objects.create(
            author=self.user,
            slug="test-random-post",
            title="Test Post",
            text="Test content",
            type=Post.TYPE_POST,
            published_at=now - timedelta(days=1),
            moderation_status=Post.MODERATION_APPROVED,
            visibility=Post.VISIBILITY_EVERYWHERE,
        )

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()

    @patch("bot.handlers.fun.render_html_message")
    @patch("bot.handlers.fun.Post.visible_objects")
    async def test_sends_random_post(self, mock_visible, mock_render):
        """Should send a random post"""
        # Mock the queryset to return our test post
        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.afirst = AsyncMock(return_value=self.post)
        mock_visible.return_value = mock_qs

        # Mock template rendering
        mock_render.return_value = "Rendered random post message"

        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/random",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Rendered random post message",
                        "parse_mode": "HTML",
                        "link_preview_options": '{"is_disabled": true}',
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_random(update, context)

        # Verify template was called with our test post
        mock_render.assert_called_once_with("channel_post_announce.html", post=self.post)

    @patch("bot.handlers.fun.render_html_message")
    @patch("bot.handlers.fun.Post.visible_objects")
    async def test_handles_no_posts_found(self, mock_visible, mock_render):
        """Should send message even when no post found"""
        # Mock the queryset to return None (no post found after 5 attempts)
        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.afirst = AsyncMock(return_value=None)
        mock_visible.return_value = mock_qs

        # Mock template rendering with None post
        mock_render.return_value = "No random post found message"

        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/random",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "No random post found message",
                        "parse_mode": "HTML",
                        "link_preview_options": '{"is_disabled": true}',
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_random(update, context)

        # Verify template was called with None post
        mock_render.assert_called_once_with("channel_post_announce.html", post=None)
