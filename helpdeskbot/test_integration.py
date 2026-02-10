"""
Integration tests for the Helpdesk Telegram bot.

Tests the bot with real Telegram library calls (no mocking of telegram lib), using:
- Mock Telegram API server (from BaseTelegramTest)
- Real helpdeskbot main() function running in webhook/polling mode
- Real Update objects created by telegram library
- Actual HTTP requests to webhook server
"""

import json
import logging
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import django
from django.conf import settings
from django.test import TestCase, override_settings

django.setup()

import requests
import telegram
from telegram import Update, Message, User as TgUser, Chat as TgChat

from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from users.models.user import User

log = logging.getLogger(__name__)


class HelpdeskBotIntegrationTest(BaseTelegramTest, TestCase):
    """Integration tests for helpdesk bot webhook and polling - runs real main()"""

    tags = {"telegram", "telegram_helpdesk", "telegram_integration"}

    # Use a different token for helpdesk bot
    HELPDESK_TOKEN = "999888777:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"

    # Telegram API responses
    SEND_MESSAGE_RESPONSE = json.dumps(
        {
            "ok": True,
            "result": {
                "message_id": 123456,
                "date": int(time.time()),
                "chat": {"id": 12345, "type": "private"},
                "text": "test",
                "from": {
                    "id": 987654321,
                    "is_bot": True,
                    "first_name": "HelpdeskBot",
                },
            },
        }
    )

    GET_ME_RESPONSE = json.dumps(
        {
            "ok": True,
            "result": {
                "id": 987654321,
                "is_bot": True,
                "first_name": "HelpdeskBot",
                "username": "helpdesk_bot",
            },
        }
    )

    SET_WEBHOOK_RESPONSE = json.dumps({"ok": True, "result": True})
    DELETE_WEBHOOK_RESPONSE = json.dumps({"ok": True, "result": True})

    updater = None

    def setUp(self):
        super().setUp()

        # Calculate the mock server base URL dynamically
        server_port = self.server.server_address[1]
        telegram_base_url = f"http://127.0.0.1:{server_port}/"

        # Create test user with active membership
        now = datetime.now(timezone.utc)
        self.test_user = User.objects.create(
            slug="test-helpdesk-user",
            email="helpdesk@example.com",
            full_name="Helpdesk Test User",
            secret_hash="helpdesk_secret_hash",
            telegram_id="888",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )

        # Patch close_old_connections to prevent 'connection is closed' errors in tests
        self.close_old_connections_patch = patch(
            "bot.handlers.common.close_old_connections"
        )
        self.close_old_connections_patch.start()

        # Override settings for helpdesk bot
        self.settings_override = override_settings(
            TELEGRAM_BASE_URL=telegram_base_url,
            DEBUG=False,
        )
        self.settings_override.enable()

        # Patch helpdesk bot config
        self.config_patches = [
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", self.HELPDESK_TOKEN),
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_WEBHOOK_URL", telegram_base_url),
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_WEBHOOK_HOST", "127.0.0.1"),
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_WEBHOOK_PORT", 8899),
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890"),
            patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_DISCUSSION_ID", "-100987654321"),
        ]
        for p in self.config_patches:
            p.start()

        self.updater = None

    def tearDown(self):
        if self.updater:
            self.updater.stop()

        # Clean up
        self.test_user.delete()
        self.close_old_connections_patch.stop()
        self.settings_override.disable()

        for p in self.config_patches:
            p.stop()

        # NB: shut down updater first, then the API (in super()):
        # in the polling mode, bot polls the API endlessly and fails with a gnarly stacktrace otherwise
        super().tearDown()

    def _create_update(
        self, message_text: str, reply_to_text: Optional[str] = None
    ) -> Update:
        """Create a real Update object using telegram library"""
        telegram_id = int(self.test_user.telegram_id or "")
        tg_user = TgUser(id=telegram_id, is_bot=False, first_name="Test")
        tg_chat = TgChat(id=12345, type="private")

        message = Message(
            message_id=1,
            date=int(time.time()),
            chat=tg_chat,
            from_user=tg_user,
            text=message_text,
            bot=self.bot,
        )

        if reply_to_text:
            reply_message = Message(
                message_id=0,
                date=int(time.time()),
                chat=tg_chat,
                text=reply_to_text,
                bot=self.bot,
                from_user=telegram.User(id=6789, is_bot=False, first_name="First"),
            )
            message.reply_to_message = reply_message

        update = Update(update_id=1, message=message, entities=123)
        return update

    def _create_command_update(self, cmd="/help") -> Update:
        update = self._create_update(cmd)
        assert isinstance(update.message, Message)
        update.message.entities.append(
            telegram.MessageEntity(type="bot_command", offset=0, length=len(cmd))
        )
        return update

    def _send_webhook_update(self, update: Update) -> requests.Response:
        """Send an update to the webhook server via HTTP POST."""
        webhook_url = f"http://127.0.0.1:8899/{self.HELPDESK_TOKEN}"
        update_dict = update.to_dict()
        try:
            response = requests.post(webhook_url, json=update_dict, timeout=5)
            return response
        except Exception as e:
            log.error(f"Failed to send webhook update: {e}")
            raise

    @override_settings(DEBUG=False)
    def test_webhook_help_command(self):
        """
        Test: Send /help command via webhook and verify bot sends help message

        Integration flow:
        1. Start bot in webhook mode (DEBUG=False)
        2. Send /help update via HTTP to webhook endpoint
        3. Verify bot calls Telegram API sendMessage
        """
        # Get server port dynamically
        server_port = self.server.server_address[1]

        # Setup expected Telegram API calls
        SEND_MESSAGE_PATH = f"/{self.HELPDESK_TOKEN}/sendMessage"

        # Use events to signal bot readiness and message sent
        webhook_ready_event = threading.Event()
        message_sent_event = threading.Event()

        def handle_send_message(request):
            message_sent_event.set()
            return self.SEND_MESSAGE_RESPONSE

        # Register routes
        self.server.add_route(f"/{self.HELPDESK_TOKEN}/getMe", lambda r: self.GET_ME_RESPONSE)
        self.server.add_route(f"/{self.HELPDESK_TOKEN}/setWebhook", lambda r: self.SET_WEBHOOK_RESPONSE)
        self.server.add_route(SEND_MESSAGE_PATH, handle_send_message)

        # Import and start the helpdesk bot
        from telegram.ext import Updater

        # Start bot in background thread
        def start_bot():
            # Import handlers inside thread to ensure patches are active
            from helpdeskbot.handlers.question import QuestionHandler
            from helpdeskbot.handlers.answers import on_reply_message
            from helpdeskbot.main import on_help_command
            from telegram.ext import CommandHandler, MessageHandler, Filters

            base_url = f"http://127.0.0.1:{server_port}/"
            self.updater = Updater(self.HELPDESK_TOKEN, use_context=True, base_url=base_url)
            dispatcher = self.updater.dispatcher

            dispatcher.add_handler(CommandHandler("help", on_help_command))
            dispatcher.add_handler(QuestionHandler("start"))
            dispatcher.add_handler(MessageHandler(Filters.reply & ~Filters.command, on_reply_message))

            self.updater.start_webhook(
                listen="127.0.0.1",
                port=8899,
                url_path=self.HELPDESK_TOKEN
            )
            self.updater.bot.set_webhook(
                url=f"http://127.0.0.1:{server_port}/{self.HELPDESK_TOKEN}"
            )
            webhook_ready_event.set()

        bot_thread = threading.Thread(target=start_bot, daemon=True)
        bot_thread.start()

        # Wait for webhook to be ready
        if not webhook_ready_event.wait(timeout=3):
            self.fail("Webhook did not start within 3 seconds")

        # Give webhook server extra time to bind
        time.sleep(0.5)

        response = self._send_webhook_update(self._create_command_update("/help"))
        self.assertIn(response.status_code, [200, 202, 204])

        # Wait for bot to send message (with timeout)
        if not message_sent_event.wait(timeout=5):
            self.fail("Bot did not send message within 5 seconds")

        # Verify the exact message sent
        send_message_requests = [r for r in self.server.requests_received if r.path == SEND_MESSAGE_PATH]
        self.assertGreaterEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertIn("Я бот Вастрик Справочной", sent_request.body["text"])
        self.assertEqual(sent_request.body["parse_mode"], "HTML")

    @override_settings(DEBUG=True)
    def test_polling_help_command(self):
        """
        Test: Send /help command via polling and verify bot sends help message

        Integration flow:
        1. Start bot in polling mode (DEBUG=True)
        2. Send /help update via Telegram API response
        3. Verify bot calls Telegram API sendMessage
        """
        # Setup expected Telegram API calls
        SEND_MESSAGE_PATH = f"/{self.HELPDESK_TOKEN}/sendMessage"
        GET_UPDATES_PATH = f"/{self.HELPDESK_TOKEN}/getUpdates"

        # Use event to signal when sendMessage is received
        message_sent_event = threading.Event()

        # State machine for getUpdates: first call returns the update, subsequent calls return empty
        get_updates_call_count = 0

        def handle_get_updates(request):
            nonlocal get_updates_call_count
            get_updates_call_count += 1

            if get_updates_call_count == 1:
                # First call: return the /help update
                return json.dumps(
                    {
                        "ok": True,
                        "result": [self._create_command_update("/help").to_dict()],
                    }
                )
            else:
                # Subsequent calls: return empty array
                # Sleep briefly to avoid busy-polling
                time.sleep(0.1)
                return json.dumps({"ok": True, "result": []})

        def handle_send_message(request):
            message_sent_event.set()
            return self.SEND_MESSAGE_RESPONSE

        # Expected requests for bot initialization (using expect_requests for synchronous handling)
        self.server.expect_requests(
            [
                ExpectedRequest(
                    Request(
                        "GET",
                        f"/{self.HELPDESK_TOKEN}/getMe",
                        {},
                    ),
                    self.GET_ME_RESPONSE,
                ),
                ExpectedRequest(
                    Request(
                        "POST",
                        f"/{self.HELPDESK_TOKEN}/deleteWebhook",
                        {},
                    ),
                    self.DELETE_WEBHOOK_RESPONSE,
                ),
            ]
        )

        # Register routes for polling
        self.server.add_route(GET_UPDATES_PATH, handle_get_updates)
        self.server.add_route(SEND_MESSAGE_PATH, handle_send_message)

        # Start bot in background thread
        def start_bot():
            # Import handlers inside thread to ensure patches are active
            from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
            from helpdeskbot.handlers.question import QuestionHandler
            from helpdeskbot.handlers.answers import on_reply_message
            from helpdeskbot.main import on_help_command

            # Get server port for base_url
            server_port = self.server.server_address[1]
            base_url = f"http://127.0.0.1:{server_port}/"

            self.updater = Updater(self.HELPDESK_TOKEN, use_context=True, base_url=base_url)
            dispatcher = self.updater.dispatcher

            dispatcher.add_handler(CommandHandler("help", on_help_command))
            dispatcher.add_handler(QuestionHandler("start"))
            dispatcher.add_handler(MessageHandler(Filters.reply & ~Filters.command, on_reply_message))

            self.updater.start_polling()

        bot_thread = threading.Thread(target=start_bot, daemon=True)
        bot_thread.start()

        # Wait for bot to poll and send message
        if not message_sent_event.wait(timeout=5):
            self.fail("Bot did not send message within 5 seconds")

        # Verify the exact message sent
        send_message_requests = [r for r in self.server.requests_received if r.path == SEND_MESSAGE_PATH]
        self.assertEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertIn("Я бот Вастрик Справочной", sent_request.body["text"])
        self.assertEqual(sent_request.body["parse_mode"], "HTML")
