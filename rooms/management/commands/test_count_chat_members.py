"""Tests for rooms/management/commands/count_chat_members.py command."""

import logging
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from telegram import Chat as TgChat
from telegram.error import TelegramError

from notifications.telegram.tests import BaseTelegramTest
from rooms.models import Room


class CountChatMembersCommandTest(BaseTelegramTest, TestCase):
    """Test the count_chat_members management command"""

    tags = {"telegram", "telegram_bot"}

    GET_CHAT_PATH = f"/{BaseTelegramTest.TOKEN}/getChat"

    def setUp(self):
        super().setUp()
        # Patch the bot in the command module to use our mock bot
        self.bot_patcher = patch("rooms.management.commands.count_chat_members.bot", self.bot)
        self.bot_patcher.start()

        # Create test rooms with chat_ids
        self.room1 = Room.objects.create(
            slug="test-room-1",
            title="Test Room 1",
            chat_id="-100123456",
            color="#FF0000",
            chat_member_count=0,  # Start with 0
        )
        self.room2 = Room.objects.create(
            slug="test-room-2",
            title="Test Room 2",
            chat_id="-100789012",
            color="#00FF00",
            chat_member_count=0,  # Start with 0
        )
        # Room without chat_id (should be skipped)
        self.room_no_chat = Room.objects.create(
            slug="test-room-no-chat",
            title="Test Room No Chat",
            chat_id=None,
            color="#0000FF",
        )

    def tearDown(self):
        self.bot_patcher.stop()
        super().tearDown()
        Room.objects.filter(slug__in=[self.room1.slug, self.room2.slug, self.room_no_chat.slug]).delete()

    def test_updates_member_counts(self):
        """Should update chat_member_count for all rooms with chat_id"""
        # Mock getChat to return chats with member counts
        call_count = {"count": 0}

        def handle_get_chat(request):
            call_count["count"] += 1
            chat_id = request.body["chat_id"]
            if chat_id == self.room1.chat_id:
                # Return chat with 42 members
                return '{"ok": true, "result": {"id": -100123456, "type": "supergroup", "title": "Test Room 1"}}'
            else:
                # Return chat with 99 members
                return '{"ok": true, "result": {"id": -100789012, "type": "supergroup", "title": "Test Room 2"}}'

        # Mock get_members_count method on Chat objects
        original_get_chat = self.bot.get_chat

        def mock_get_chat(chat_id, *args, **kwargs):
            chat = original_get_chat(chat_id, *args, **kwargs)
            # Patch get_members_count on the returned chat
            if chat_id == self.room1.chat_id:
                chat.get_members_count = lambda: 42
            else:
                chat.get_members_count = lambda: 99
            return chat

        self.bot.get_chat = mock_get_chat

        self.server.add_route(self.GET_CHAT_PATH, handle_get_chat)

        # Capture stdout
        out = StringIO()
        call_command("count_chat_members", stdout=out)

        # Verify output
        self.assertIn("Done 🥙", out.getvalue())

        # Verify getChat was called for both rooms with chat_id
        get_chat_requests = [r for r in self.server.requests_received if r.path == self.GET_CHAT_PATH]
        self.assertEqual(len(get_chat_requests), 2)
        chat_ids = {r.body["chat_id"] for r in get_chat_requests}
        self.assertEqual(chat_ids, {self.room1.chat_id, self.room2.chat_id})

        # Verify member counts were updated in database
        self.room1.refresh_from_db()
        self.room2.refresh_from_db()
        self.assertEqual(self.room1.chat_member_count, 42)
        self.assertEqual(self.room2.chat_member_count, 99)

        # Verify room without chat_id was not updated
        self.room_no_chat.refresh_from_db()
        self.assertEqual(self.room_no_chat.chat_member_count, 0)

    def test_handles_telegram_error(self):
        """Should handle TelegramError and continue to next room"""
        # Mock get_chat to raise TelegramError for first room, succeed for second
        original_get_chat = self.bot.get_chat
        call_count = {"count": 0}

        def mock_get_chat(chat_id, *args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First call (room1) - raise TelegramError
                raise TelegramError("Bad Request: chat not found")
            else:
                # Second call (room2) - succeed
                chat = original_get_chat(chat_id, *args, **kwargs)
                chat.get_members_count = lambda: 99
                return chat

        self.bot.get_chat = mock_get_chat

        # Set up route for successful getChat (room2)
        def handle_get_chat(request):
            return '{"ok": true, "result": {"id": -100789012, "type": "supergroup", "title": "Test Room 2"}}'

        self.server.add_route(self.GET_CHAT_PATH, handle_get_chat)

        # Capture stdout and logs
        out = StringIO()
        with self.assertLogs("rooms.management.commands.count_chat_members", level=logging.WARNING) as logs:
            call_command("count_chat_members", stdout=out)

        # Verify warning was logged
        self.assertTrue(any("Failed to get member count" in log for log in logs.output))

        # Verify getChat was called once via HTTP (for room2)
        get_chat_requests = [r for r in self.server.requests_received if r.path == self.GET_CHAT_PATH]
        self.assertEqual(len(get_chat_requests), 1)

        # Verify room1 was not updated (error), but room2 was
        self.room1.refresh_from_db()
        self.room2.refresh_from_db()
        self.assertEqual(self.room1.chat_member_count, 0)  # Not updated
        self.assertEqual(self.room2.chat_member_count, 99)  # Updated

        # Verify command still completed
        self.assertIn("Done 🥙", out.getvalue())
