"""
Integration tests for the Helpdesk Telegram bot.

Tests the bot with real Telegram library calls (no mocking of telegram lib), using:
- Mock Telegram API server (from BaseTelegramTest)
- Real helpdeskbot main() function running in webhook/polling mode
- Real Update objects created by telegram library
- Actual HTTP requests to webhook server
"""

import asyncio
import httpx
import json
import logging
import socket
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

import telegram
from telegram import Update, Message, User as TgUser, Chat as TgChat

from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from users.models.user import User

log = logging.getLogger(__name__)


def wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Wait for a TCP port to be listening."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


class HelpdeskBotIntegrationTest(BaseTelegramTest, TestCase):
    """Integration tests for helpdesk bot webhook and polling - runs real main()"""

    tags = {"telegram", "telegram_helpdesk", "telegram_integration"}

    # Use a different token for helpdesk bot
    HELPDESK_TOKEN = "987654321:kjihgfedcbAzyxWvutsrqpOnmlkjihGfeDCBA"

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

    bot_server = None

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

        self.bot_server = None

    def tearDown(self):
        # Note: Can't use async tearDown as Django test framework doesn't support it
        # Bot server cleanup is handled in test methods themselves
        if self.bot_server:
            # Skip async stop - will be garbage collected
            pass

        # Clean up
        self.test_user.delete()
        self.close_old_connections_patch.stop()
        self.settings_override.disable()

        for p in self.config_patches:
            p.stop()

        # NB: shut down bot_server first, then the API (in super()):
        # in the polling mode, bot polls the API endlessly and fails with a gnarly stacktrace otherwise
        super().tearDown()

    def _create_update(
        self, message_text: str, reply_to_text: Optional[str] = None
    ) -> Update:
        """Create a real Update object using telegram library"""
        telegram_id = int(self.test_user.telegram_id or "")
        tg_user = TgUser(id=telegram_id, is_bot=False, first_name="Test")
        tg_chat = TgChat(id=12345, type="private")
        tg_chat.set_bot(self.bot)

        message = Message(
            message_id=1,
            date=int(time.time()),
            chat=tg_chat,
            from_user=tg_user,
            text=message_text,
        )
        message.set_bot(self.bot)

        if reply_to_text:
            reply_message = Message(
                message_id=0,
                date=int(time.time()),
                chat=tg_chat,
                text=reply_to_text,
                from_user=telegram.User(id=6789, is_bot=False, first_name="First"),
            )
            reply_message.set_bot(self.bot)
            message.reply_to_message = reply_message

        update = Update(update_id=1, message=message)
        return update

    def _create_command_update(self, cmd="/help") -> Update:
        """Create a real Update object with a command"""
        telegram_id = int(self.test_user.telegram_id or "")
        tg_user = TgUser(id=telegram_id, is_bot=False, first_name="Test")
        tg_chat = TgChat(id=12345, type="private")
        tg_chat.set_bot(self.bot)

        entity = telegram.MessageEntity(type="bot_command", offset=0, length=len(cmd))

        message = Message(
            message_id=1,
            date=int(time.time()),
            chat=tg_chat,
            from_user=tg_user,
            text=cmd,
            entities=(entity,),  # v20+ entities is a tuple
        )
        message.set_bot(self.bot)

        return Update(update_id=1, message=message)

    async def _send_webhook_update(self, update: Update) -> httpx.Response:
        """Send an update to the webhook server via HTTP POST."""
        webhook_url = f"http://127.0.0.1:8899/{self.HELPDESK_TOKEN}"
        update_dict = update.to_dict()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=update_dict, timeout=5.0)
                return response
        except Exception as e:
            log.error(f"Failed to send webhook update: {e}")
            raise

    @override_settings(DEBUG=False)
    async def test_webhook_help_command(self):
        """
        Test: Send /help command via webhook and verify bot sends help message

        Integration flow:
        1. Start bot in webhook mode (DEBUG=False) in separate thread
        2. Send /help update via HTTP to webhook endpoint
        3. Verify bot calls Telegram API sendMessage
        """
        # Get server port dynamically
        server_port = self.server.server_address[1]

        # Setup expected Telegram API calls
        SEND_MESSAGE_PATH = f"/{self.HELPDESK_TOKEN}/sendMessage"

        # Use events to signal message sent
        message_sent = threading.Event()
        sent_messages = []

        def handle_send_message(request):
            log.info(f"handle_send_message called with chat_id={request.body.get('chat_id')}")
            sent_messages.append(request.body)
            message_sent.set()
            return self.SEND_MESSAGE_RESPONSE

        # Register routes
        self.server.add_route(f"/{self.HELPDESK_TOKEN}/getMe", lambda r: self.GET_ME_RESPONSE)
        self.server.add_route(f"/{self.HELPDESK_TOKEN}/setWebhook", lambda r: self.SET_WEBHOOK_RESPONSE)
        self.server.add_route(SEND_MESSAGE_PATH, handle_send_message)

        # Run webhook in separate thread with its own event loop
        webhook_started = threading.Event()
        webhook_error = []

        def run_webhook_in_thread():
            """Run webhook server in a new event loop"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Import handlers inside thread to ensure patches are active
                from helpdeskbot.handlers.question import QuestionHandler
                from helpdeskbot.handlers.answers import on_reply_message
                from helpdeskbot.main import on_help_command
                from telegram.ext import Application, CommandHandler, MessageHandler, filters

                base_url = f"http://127.0.0.1:{server_port}/"

                async def start_webhook():
                    application = Application.builder().token(self.HELPDESK_TOKEN).base_url(base_url).build()

                    application.add_handler(CommandHandler("help", on_help_command))
                    application.add_handler(QuestionHandler("start"))
                    application.add_handler(MessageHandler(filters.REPLY & ~filters.COMMAND, on_reply_message))

                    await application.initialize()
                    await application.start()
                    await application.updater.start_webhook(
                        listen="127.0.0.1",
                        port=8899,
                        url_path=self.HELPDESK_TOKEN
                    )
                    webhook_started.set()
                    # Keep the event loop alive
                    await asyncio.Event().wait()

                loop.run_until_complete(start_webhook())
            except Exception as e:
                log.error(f"Webhook thread failed: {e}", exc_info=True)
                webhook_error.append(e)
            finally:
                loop.close()

        webhook_thread = threading.Thread(target=run_webhook_in_thread, daemon=True)
        webhook_thread.start()

        try:
            # Wait for webhook thread to start
            if not webhook_started.wait(timeout=2.0):
                self.fail("Webhook thread did not start")

            if webhook_error:
                self.fail(f"Webhook failed to start: {webhook_error[0]}")

            # Wait for the webhook server to be ready (listening on port)
            if not wait_for_port("127.0.0.1", 8899, timeout=10.0):
                if webhook_error:
                    self.fail(f"Webhook server failed: {webhook_error[0]}")
                self.fail("Webhook server did not start listening on port 8899")

            # Send webhook update
            response = await self._send_webhook_update(self._create_command_update("/help"))
            self.assertIn(response.status_code, [200, 202, 204])

            # Wait for the handler to send the message
            if not message_sent.wait(timeout=10.0):
                log.error(f"Mock server received these paths: {[r.path for r in self.server.requests_received]}")
                self.fail("Bot did not send message within 10 seconds")

            # Verify the message was sent correctly
            self.assertEqual(len(sent_messages), 1, "Should have sent exactly one message")
            sent_msg = sent_messages[0]
            self.assertEqual(sent_msg["chat_id"], "12345")
            self.assertIn("Я бот Вастрик Справочной", sent_msg["text"])
            self.assertEqual(sent_msg["parse_mode"], "HTML")
        finally:
            # Clean up: let the daemon thread be killed on test exit
            pass

    @override_settings(DEBUG=True)
    async def test_polling_help_command(self):
        """
        Test: Send /help command via polling and verify bot sends help message

        Integration flow:
        1. Start bot in polling mode (DEBUG=True) in separate thread
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

        # Expected requests for bot initialization
        self.server.expect_requests(
            [
                ExpectedRequest(
                    Request(
                        "POST",  # v20+ uses POST for all API calls
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

        # Get server port for base_url
        server_port = self.server.server_address[1]

        # Run polling in separate thread with its own event loop
        polling_started = threading.Event()
        polling_error = []

        def run_polling_in_thread():
            """Run polling in a new event loop"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Import handlers inside thread to ensure patches are active
                from helpdeskbot.handlers.question import QuestionHandler
                from helpdeskbot.handlers.answers import on_reply_message
                from helpdeskbot.main import on_help_command
                from telegram.ext import Application, CommandHandler, MessageHandler, filters

                base_url = f"http://127.0.0.1:{server_port}/"

                async def start_polling():
                    application = Application.builder().token(self.HELPDESK_TOKEN).base_url(base_url).build()

                    application.add_handler(CommandHandler("help", on_help_command))
                    application.add_handler(QuestionHandler("start"))
                    application.add_handler(MessageHandler(filters.REPLY & ~filters.COMMAND, on_reply_message))

                    async with application:
                        await application.start()
                        await application.updater.start_polling()
                        polling_started.set()
                        await asyncio.Event().wait()  # Run forever

                loop.run_until_complete(start_polling())
            except Exception as e:
                log.error(f"Polling thread failed: {e}", exc_info=True)
                polling_error.append(e)
            finally:
                loop.close()

        polling_thread = threading.Thread(target=run_polling_in_thread, daemon=True)
        polling_thread.start()

        try:
            # Wait for polling thread to start
            if not polling_started.wait(timeout=2.0):
                self.fail("Polling thread did not start")

            if polling_error:
                self.fail(f"Polling failed to start: {polling_error[0]}")

            # Wait for bot to send message (with timeout)
            if not message_sent_event.wait(timeout=10):
                self.fail("Bot did not send message within 10 seconds")

            # Verify the exact message sent
            send_message_requests = [r for r in self.server.requests_received if r.path == SEND_MESSAGE_PATH]
            self.assertEqual(len(send_message_requests), 1)

            sent_request = send_message_requests[0]
            self.assertEqual(sent_request.body["chat_id"], "12345")
            self.assertIn("Я бот Вастрик Справочной", sent_request.body["text"])
            self.assertEqual(sent_request.body["parse_mode"], "HTML")
        finally:
            # Clean up: let the daemon thread be killed on test exit
            pass
