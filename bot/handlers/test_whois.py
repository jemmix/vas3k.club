"""Tests for bot/handlers/whois.py handlers."""

from unittest.mock import patch, MagicMock

from telegram.ext import CallbackContext

from django.test import TestCase
from telegram import User as TgUser, Chat as TgChat

from bot.handlers.whois import command_whois
from bot.test_helpers import (
    create_test_user,
    create_command_update,
    SEND_MESSAGE_RESPONSE,
)
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request


class CommandWhoisTest(BaseTelegramTest, TestCase):
    """Test the command_whois handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()

        # Mock close_old_connections BEFORE creating users
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

        # Mock close_old_connections from django.db (used by ensure_fresh_db_connection decorator)
        self.django_close_patch = patch("bot.decorators.close_old_connections")
        self.django_close_patch.start()

        self.user = create_test_user(telegram_id="111", slug="test-user")
        self.target_user = create_test_user(telegram_id="222", slug="target-user", full_name="Target User")

        # Mock cached_telegram_users for @is_club_member decorator
        self.cached_users_patch = patch("bot.decorators.cached_telegram_users")
        self.mock_cached_users = self.cached_users_patch.start()
        self.mock_cached_users.return_value = {str(self.user.telegram_id): self.user.id}

    def tearDown(self):
        super().tearDown()
        self.target_user.delete()
        self.user.delete()
        self.close_old_connections_patch.stop()
        self.django_close_patch.stop()
        self.cached_users_patch.stop()

    def test_no_reply_or_forward(self):
        """Should reject command without reply or forward"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/whois",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Эту команду нужно вызывать реплаем на сообщение человека, о котором вы хотите узнать",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        command_whois(update, context)

    def test_reply_to_bot(self):
        """Should reject whois on bot"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/whois",
        )
        # Add reply to bot message (without sender_chat attribute)
        bot_user = TgUser(id=999, is_bot=True, first_name="Bot")
        # Use spec to limit attributes so sender_chat doesn't exist
        reply_message = MagicMock(spec=['from_user', 'forward_date'])
        reply_message.from_user = bot_user
        reply_message.forward_date = None
        update.message.reply_to_message = reply_message

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Это бот, глупышка",
                        "reply_to_message_id": "1",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        command_whois(update, context)

    def test_user_not_in_club(self):
        """Should report when user not found in club"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/whois",
        )
        # Add reply from unknown user
        unknown_user = TgUser(id=999, is_bot=False, first_name="Unknown")
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.from_user = unknown_user
        update.message.reply_to_message.forward_date = None

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Пользователь не найден в Клубе. Гоните его, насмехайтесь над ним!",
                        "reply_to_message_id": "1",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        command_whois(update, context)

    def test_successful_whois(self):
        """Should return user profile for club member"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/whois",
        )
        # Add reply from target user
        target_tg_user = TgUser(id=222, is_bot=False, first_name="Target")
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.from_user = target_tg_user
        update.message.reply_to_message.forward_date = None

        context = MagicMock(spec=CallbackContext)

        expected_url = f"http://127.0.0.1:8000/user/{self.target_user.slug}/"
        expected_text = f'Кажется, это <a href="{expected_url}">{self.target_user.full_name}</a>'

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": expected_text,
                        "parse_mode": "HTML",
                        "reply_to_message_id": "1",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        command_whois(update, context)

    def test_forwarded_message_hidden_profile(self):
        """Should handle forwarded message with hidden profile"""
        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/whois",
        )
        update.message.chat = TgChat(id=12345, type=TgChat.PRIVATE, bot=self.bot)
        # Forwarded message without forward_from (hidden profile)
        update.message.forward_date = 123456
        update.message.forward_from = None
        update.message.forward_sender_name = "Скрытый Юзер"

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Кажется, Скрытый Юзер скрыл свой профиль для пересылаемых сообщений. Попробуй дать команду в ответ на исходное сообщение",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        command_whois(update, context)
