"""Tests for bot decorators (is_moderator, is_club_member)."""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from telegram.ext import CallbackContext

from bot.decorators import is_moderator, is_club_member
from bot.test_helpers import (
    create_message_update,
    create_callback_query_update,
    SEND_MESSAGE_RESPONSE,
    ANSWER_CALLBACK_QUERY_RESPONSE,
    create_test_user,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from users.models.user import User


class IsModeratorDecoratorTest(BaseTelegramTest, TestCase):
    """Test the is_moderator decorator"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.moderator = create_test_user(
            telegram_id="111",
            full_name="Moderator User",
            roles=[User.ROLE_MODERATOR],
        )
        self.regular_user = create_test_user(
            telegram_id="222",
            full_name="Regular User",
            roles=[],
        )

        self.close_old_connections_patch = patch("bot.decorators.close_old_connections")
        self.close_old_connections_patch.start()

    def tearDown(self):
        super().tearDown()
        self.moderator.delete()
        self.regular_user.delete()
        self.close_old_connections_patch.stop()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_allows_moderator_in_admin_chat(self):
        """Moderator in admin chat should be allowed"""
        mock_handler = MagicMock(return_value="success")
        decorated_handler = is_moderator(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        # No HTTP requests expected - handler should execute directly
        result = await decorated_handler(update, context)

        self.assertEqual(result, "success")
        mock_handler.assert_called_once_with(update, context)

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_non_admin_chat(self):
        """Should reject when not in admin chat"""
        mock_handler = MagicMock()
        decorated_handler = is_moderator(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=99999,  # Wrong chat
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "99999",
                        "text": "❌ Для этого действия нужно быть в чате модераторов",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(chat_id=99999),
            )
        ])

        result = await decorated_handler(update, context)

        self.assertIsNone(result)
        mock_handler.assert_not_called()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_non_moderator(self):
        """Should reject regular user even in admin chat"""
        mock_handler = MagicMock()
        decorated_handler = is_moderator(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=222,  # Regular user
            chat_id=12345,
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "⚠️ 'Test' не модератор или не привязал бота к аккаунту",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        result = await decorated_handler(update, context)

        self.assertIsNone(result)
        mock_handler.assert_not_called()

    @override_settings(TELEGRAM_ADMIN_CHAT_ID=12345)
    async def test_rejects_unknown_telegram_user(self):
        """Should reject user not in database"""
        mock_handler = MagicMock()
        decorated_handler = is_moderator(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=999999,  # Unknown user
            chat_id=12345,
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "⚠️ 'Test' не модератор или не привязал бота к аккаунту",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        result = await decorated_handler(update, context)

        self.assertIsNone(result)
        mock_handler.assert_not_called()


class IsClubMemberDecoratorTest(BaseTelegramTest, TestCase):
    """Test the is_club_member decorator"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.member_user = create_test_user(
            telegram_id="333",
            full_name="Member User",
        )

    def tearDown(self):
        super().tearDown()
        self.member_user.delete()

    @patch("bot.decorators.cached_telegram_users")
    async def test_allows_club_member(self, mock_cached_users):
        """Club member should be allowed"""
        mock_cached_users.return_value = {"333": self.member_user}
        mock_handler = MagicMock(return_value="success")
        decorated_handler = is_club_member(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=333,
            chat_id=12345,
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        result = await decorated_handler(update, context)

        self.assertEqual(result, "success")
        mock_handler.assert_called_once_with(update, context)

    @patch("bot.decorators.cached_telegram_users")
    async def test_rejects_non_member_via_message(self, mock_cached_users):
        """Non-member via message should get reply_text"""
        mock_cached_users.return_value = {}  # Empty cache
        mock_handler = MagicMock()
        decorated_handler = is_club_member(mock_handler)

        update = create_message_update(
            bot=self.bot,
            telegram_id=444,
            chat_id=12345,
            text="Test message",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "☝️ Привяжи <a href=\"https://vas3k.club/user/me/edit/bot/\">бота</a> к профилю, братишка",
                        "parse_mode": "HTML",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        result = await decorated_handler(update, context)

        self.assertIsNone(result)
        mock_handler.assert_not_called()

    @patch("bot.decorators.cached_telegram_users")
    async def test_rejects_non_member_via_callback_query(self, mock_cached_users):
        """Non-member via callback_query should get answer"""
        mock_cached_users.return_value = {}  # Empty cache
        mock_handler = MagicMock()
        decorated_handler = is_club_member(mock_handler)

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=555,
            chat_id=12345,
            data="test_callback",
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "☝️ Привяжи бота к профилю, братишка",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            )
        ])

        result = await decorated_handler(update, context)

        self.assertIsNone(result)
        mock_handler.assert_not_called()
