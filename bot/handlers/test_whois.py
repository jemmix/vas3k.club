"""Tests for bot/handlers/whois.py handlers."""

import time
from unittest.mock import patch, MagicMock

from telegram import Message
from telegram.ext import CallbackContext

from django.test import TestCase
from telegram import User as TgUser, Chat as TgChat

from bot.handlers.whois import command_whois
from bot.test_helpers import (
    create_test_user,
    create_command_update,
    create_reply_update,
    create_message_update,
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

    async def test_no_reply_or_forward(self):
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
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_whois(update, context)

    async def test_reply_to_bot(self):
        """Should reject whois on bot"""
        # Create a reply update where user replies to a bot message
        # We need to manually create this since the bot user needs is_bot=True
        reply_to_dict = {
            "message_id": 100,
            "date": int(time.time()) - 100,
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 999, "is_bot": True, "first_name": "Bot"},
            "text": "Bot message",
        }
        reply_to_message = Message.de_json(reply_to_dict, self.bot)

        update = create_message_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="/whois",
            reply_to_message=reply_to_message,
        )

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Это бот, глупышка",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_whois(update, context)

    async def test_user_not_in_club(self):
        """Should report when user not found in club"""
        # Create a reply update where user replies to unknown user (telegram_id=999, not in club)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="/whois",
            reply_to_text="Message from unknown user",
            reply_to_user_id=999,  # This user is not in the club
        )

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Пользователь не найден в Клубе. Гоните его, насмехайтесь над ним!",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_whois(update, context)

    async def test_successful_whois(self):
        """Should return user profile for club member"""
        # Create a reply update where user runs /whois command replying to target user's message
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="/whois",
            reply_to_text="Some message from target",
            reply_to_user_id=222,
        )

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
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_whois(update, context)

    async def test_forwarded_message_hidden_profile(self):
        """Should handle forwarded message with hidden profile"""
        # Create a forwarded message with hidden profile using de_json
        # In v20+, forwarded messages use forward_origin
        from telegram import Update

        forward_date = int(time.time()) - 100
        message_dict = {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 111, "is_bot": False, "first_name": "Test"},
            "text": "/whois",
            "forward_origin": {
                "type": "hidden_user",
                "date": forward_date,
                "sender_user_name": "Скрытый Юзер"
            }
        }
        message = Message.de_json(message_dict, self.bot)
        update = Update(update_id=1, message=message)

        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Кажется, Скрытый Юзер скрыл свой профиль для пересылаемых сообщений. Попробуй дать команду в ответ на исходное сообщение",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_whois(update, context)
