"""Tests for bot/handlers/auth.py command_auth handler."""

from unittest.mock import patch, MagicMock

from django.test import TestCase
from telegram.ext import CallbackContext

from bot.handlers.auth import command_auth
from bot.test_helpers import (
    create_test_user,
    create_command_update,
    DELETE_MESSAGE_RESPONSE,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from users.models.user import User


class CommandAuthTest(BaseTelegramTest, TestCase):
    """Test the command_auth handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    DELETE_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/deleteMessage"

    def setUp(self):
        super().setUp()
        self.user_approved = create_test_user(
            secret_hash="approved_secret_123",
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        self.user_unapproved = create_test_user(
            secret_hash="unapproved_secret_456",
            moderation_status=User.MODERATION_STATUS_ON_REVIEW,
        )

        # Mock cache functions
        self.flush_cache_patch = patch("bot.handlers.auth.flush_users_cache")
        self.cached_users_patch = patch("bot.handlers.auth.cached_telegram_users")
        self.close_db_patch = patch("bot.decorators.close_old_connections")

        self.flush_cache_patch.start()
        self.cached_users_patch.start()
        self.close_db_patch.start()

    def tearDown(self):
        super().tearDown()
        self.user_approved.delete()
        self.user_unapproved.delete()
        self.flush_cache_patch.stop()
        self.cached_users_patch.stop()
        self.close_db_patch.stop()

    async def test_no_code_provided(self):
        """Should send error message when no code provided"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/auth",
            args="",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "☝️ Нужно прислать мне секретный код. Напиши /auth и код из <a href=\"https://vas3k.club/user/me/edit/bot/\">профиля в Клубе</a> через пробел. Только не публикуй его в публичных чатах!",
                        "parse_mode": "HTML",
                        "disable_notification": "False",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
        ])

        await command_auth(update, context)

    async def test_invalid_code(self):
        """Should send error message for invalid code"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/auth",
            args="invalid_code_xyz",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Пользователь с таким кодом не найден",
                        "disable_notification": "False",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
        ])

        await command_auth(update, context)

    async def test_success_approved_user(self):
        """Should link approved user and delete message"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/auth",
            args="approved_secret_123",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"Отличный код! Приятно познакомиться, {self.user_approved.slug}",
                        "disable_notification": "False",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.DELETE_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "1",
                    },
                ),
                DELETE_MESSAGE_RESPONSE(),
            ),
        ])

        await command_auth(update, context)

        # Verify user was updated
        self.user_approved.refresh_from_db()
        self.assertEqual(self.user_approved.telegram_id, "111")
        self.assertIsNotNone(self.user_approved.telegram_data)

    async def test_success_unapproved_user(self):
        """Should link unapproved user and send moderation message"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=12345,
            command="/auth",
            args="unapproved_secret_456",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"Отличный код! Приятно познакомиться, {self.user_unapproved.slug}",
                        "disable_notification": "False",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.DELETE_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "message_id": "1",
                    },
                ),
                DELETE_MESSAGE_RESPONSE(),
            ),
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Теперь осталось пройти модерацию. Бот заработает сразу после этого",
                        "disable_notification": "False",
                    },
                ),
                '{"ok": true, "result": {"message_id": 123457, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}',
            ),
        ])

        await command_auth(update, context)

        # Verify user was updated
        self.user_unapproved.refresh_from_db()
        self.assertEqual(self.user_unapproved.telegram_id, "222")
        self.assertIsNotNone(self.user_unapproved.telegram_data)
