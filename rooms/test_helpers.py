"""Tests for rooms/helpers.py functions."""

import logging
from unittest.mock import patch, MagicMock

from django.test import TestCase
from telegram import ChatMember, User as TgUser
from telegram.error import TelegramError

from bot.test_helpers import create_test_user
from notifications.telegram.tests import BaseTelegramTest
from rooms.helpers import ban_user_in_all_chats, unban_user_in_all_chats
from rooms.models import Room


class BanUserInAllChatsTest(BaseTelegramTest, TestCase):
    """Test the ban_user_in_all_chats function"""

    tags = {"telegram", "telegram_bot"}

    GET_CHAT_MEMBER_PATH = f"/{BaseTelegramTest.TOKEN}/getChatMember"
    KICK_CHAT_MEMBER_PATH = f"/{BaseTelegramTest.TOKEN}/kickChatMember"
    UNBAN_CHAT_MEMBER_PATH = f"/{BaseTelegramTest.TOKEN}/unbanChatMember"

    def setUp(self):
        super().setUp()
        # Patch the bot in rooms.helpers to use our mock bot
        self.bot_patcher = patch("rooms.helpers.bot", self.bot)
        self.bot_patcher.start()

        self.user = create_test_user(telegram_id="111")

        # Create test rooms with chat_ids
        self.room1 = Room.objects.create(
            slug="test-room-1",
            title="Test Room 1",
            chat_id="-100123456",
            color="#FF0000",
        )
        self.room2 = Room.objects.create(
            slug="test-room-2",
            title="Test Room 2",
            chat_id="-100789012",
            color="#00FF00",
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
        self.user.delete()

    def test_bans_user_permanently(self):
        """Should ban user in all chats with chat_id"""
        # Mock getChatMember to return a member
        def handle_get_chat_member(request):
            return '{"ok": true, "result": {"user": {"id": 111, "is_bot": false, "first_name": "Test"}, "status": "member"}}'

        # Mock kickChatMember to return success
        def handle_kick_chat_member(request):
            return '{"ok": true, "result": true}'

        self.server.add_route(self.GET_CHAT_MEMBER_PATH, handle_get_chat_member)
        self.server.add_route(self.KICK_CHAT_MEMBER_PATH, handle_kick_chat_member)

        ban_user_in_all_chats(self.user, is_permanent=True)

        # Verify getChatMember was called for both rooms
        get_member_requests = [r for r in self.server.requests_received if r.path == self.GET_CHAT_MEMBER_PATH]
        self.assertEqual(len(get_member_requests), 2)
        chat_ids = {r.body["chat_id"] for r in get_member_requests}
        self.assertEqual(chat_ids, {self.room1.chat_id, self.room2.chat_id})

        # Verify kickChatMember was called for both rooms
        kick_requests = [r for r in self.server.requests_received if r.path == self.KICK_CHAT_MEMBER_PATH]
        self.assertEqual(len(kick_requests), 2)
        kick_chat_ids = {r.body["chat_id"] for r in kick_requests}
        self.assertEqual(kick_chat_ids, {self.room1.chat_id, self.room2.chat_id})

        # Verify unbanChatMember was NOT called (permanent ban)
        unban_requests = [r for r in self.server.requests_received if r.path == self.UNBAN_CHAT_MEMBER_PATH]
        self.assertEqual(len(unban_requests), 0)

    def test_bans_user_non_permanently(self):
        """Should ban then immediately unban user (kick from chat)"""
        # Mock getChatMember to return a member
        def handle_get_chat_member(request):
            return '{"ok": true, "result": {"user": {"id": 111, "is_bot": false, "first_name": "Test"}, "status": "member"}}'

        # Mock kickChatMember to return success
        def handle_kick_chat_member(request):
            return '{"ok": true, "result": true}'

        # Mock unbanChatMember to return success
        def handle_unban_chat_member(request):
            return '{"ok": true, "result": true}'

        self.server.add_route(self.GET_CHAT_MEMBER_PATH, handle_get_chat_member)
        self.server.add_route(self.KICK_CHAT_MEMBER_PATH, handle_kick_chat_member)
        self.server.add_route(self.UNBAN_CHAT_MEMBER_PATH, handle_unban_chat_member)

        ban_user_in_all_chats(self.user, is_permanent=False)

        # Verify getChatMember was called
        get_member_requests = [r for r in self.server.requests_received if r.path == self.GET_CHAT_MEMBER_PATH]
        self.assertEqual(len(get_member_requests), 2)

        # Verify kickChatMember was called
        kick_requests = [r for r in self.server.requests_received if r.path == self.KICK_CHAT_MEMBER_PATH]
        self.assertEqual(len(kick_requests), 2)

        # Verify unbanChatMember WAS called (non-permanent ban = kick)
        unban_requests = [r for r in self.server.requests_received if r.path == self.UNBAN_CHAT_MEMBER_PATH]
        self.assertEqual(len(unban_requests), 2)
        unban_chat_ids = {r.body["chat_id"] for r in unban_requests}
        self.assertEqual(unban_chat_ids, {self.room1.chat_id, self.room2.chat_id})

    def test_handles_user_without_telegram_id(self):
        """Should skip user without telegram_id and log warning"""
        user_no_telegram = create_test_user(telegram_id=None, slug="no-telegram-user")

        with self.assertLogs("rooms.helpers", level=logging.WARNING) as logs:
            ban_user_in_all_chats(user_no_telegram)

        # Verify warning was logged
        self.assertTrue(any("has no telegram_id" in log for log in logs.output))

        # Verify no API calls were made
        self.assertEqual(len(self.server.requests_received), 0)

        user_no_telegram.delete()

    def test_handles_telegram_error(self):
        """Should handle TelegramError and continue to next room"""
        # Mock get_chat_member to raise TelegramError for first room, succeed for second
        original_get_chat_member = self.bot.get_chat_member
        call_count = {"count": 0}

        def mock_get_chat_member(chat_id, user_id, *args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First call (room1) - raise TelegramError
                raise TelegramError("Bad Request: user not found")
            else:
                # Second call (room2) - use real method
                return original_get_chat_member(chat_id, user_id, *args, **kwargs)

        self.bot.get_chat_member = mock_get_chat_member

        # Set up route for successful kick
        def handle_kick_chat_member(request):
            return '{"ok": true, "result": true}'

        self.server.add_route(self.KICK_CHAT_MEMBER_PATH, handle_kick_chat_member)

        # Need route for getChatMember for second room
        def handle_get_chat_member(request):
            return '{"ok": true, "result": {"user": {"id": 111, "is_bot": false, "first_name": "Test"}, "status": "member"}}'

        self.server.add_route(self.GET_CHAT_MEMBER_PATH, handle_get_chat_member)

        with self.assertLogs("rooms.helpers", level=logging.WARNING) as logs:
            ban_user_in_all_chats(self.user)

        # Verify warning was logged
        self.assertTrue(any("Failed to ban user" in log for log in logs.output))

        # Verify getChatMember was called once via HTTP (for room2)
        get_member_requests = [r for r in self.server.requests_received if r.path == self.GET_CHAT_MEMBER_PATH]
        self.assertEqual(len(get_member_requests), 1)

        # Verify kickChatMember was only called for room2 (room1 failed)
        kick_requests = [r for r in self.server.requests_received if r.path == self.KICK_CHAT_MEMBER_PATH]
        self.assertEqual(len(kick_requests), 1)


class UnbanUserInAllChatsTest(BaseTelegramTest, TestCase):
    """Test the unban_user_in_all_chats function"""

    tags = {"telegram", "telegram_bot"}

    UNBAN_CHAT_MEMBER_PATH = f"/{BaseTelegramTest.TOKEN}/unbanChatMember"

    def setUp(self):
        super().setUp()
        # Patch the bot in rooms.helpers to use our mock bot
        self.bot_patcher = patch("rooms.helpers.bot", self.bot)
        self.bot_patcher.start()

        self.user = create_test_user(telegram_id="111")

        # Create test rooms with chat_ids
        self.room1 = Room.objects.create(
            slug="test-room-1",
            title="Test Room 1",
            chat_id="-100123456",
            color="#FF0000",
        )
        self.room2 = Room.objects.create(
            slug="test-room-2",
            title="Test Room 2",
            chat_id="-100789012",
            color="#00FF00",
        )

    def tearDown(self):
        self.bot_patcher.stop()
        super().tearDown()
        Room.objects.filter(slug__in=[self.room1.slug, self.room2.slug]).delete()
        self.user.delete()

    def test_unbans_user_in_all_chats(self):
        """Should unban user in all chats with chat_id"""
        # Mock unbanChatMember to return success
        def handle_unban_chat_member(request):
            return '{"ok": true, "result": true}'

        self.server.add_route(self.UNBAN_CHAT_MEMBER_PATH, handle_unban_chat_member)

        unban_user_in_all_chats(self.user)

        # Verify unbanChatMember was called for both rooms
        unban_requests = [r for r in self.server.requests_received if r.path == self.UNBAN_CHAT_MEMBER_PATH]
        self.assertEqual(len(unban_requests), 2)
        chat_ids = {r.body["chat_id"] for r in unban_requests}
        self.assertEqual(chat_ids, {self.room1.chat_id, self.room2.chat_id})

        # Verify user_id is correct
        user_ids = {r.body["user_id"] for r in unban_requests}
        self.assertEqual(user_ids, {str(self.user.telegram_id)})

    def test_handles_user_without_telegram_id(self):
        """Should skip user without telegram_id and log warning"""
        user_no_telegram = create_test_user(telegram_id=None, slug="no-telegram-user")

        with self.assertLogs("rooms.helpers", level=logging.WARNING) as logs:
            unban_user_in_all_chats(user_no_telegram)

        # Verify warning was logged
        self.assertTrue(any("has no telegram_id" in log for log in logs.output))

        # Verify no API calls were made
        self.assertEqual(len(self.server.requests_received), 0)

        user_no_telegram.delete()

    def test_handles_telegram_error(self):
        """Should handle TelegramError and continue to next room"""
        # Mock unban_chat_member to raise TelegramError for first room, succeed for second
        original_unban_chat_member = self.bot.unban_chat_member
        call_count = {"count": 0}

        def mock_unban_chat_member(chat_id, user_id, *args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First call (room1) - raise TelegramError
                raise TelegramError("Bad Request: user is not a member")
            else:
                # Second call (room2) - use real method
                return original_unban_chat_member(chat_id, user_id, *args, **kwargs)

        self.bot.unban_chat_member = mock_unban_chat_member

        # Set up route for successful unban (room2)
        def handle_unban_chat_member(request):
            return '{"ok": true, "result": true}'

        self.server.add_route(self.UNBAN_CHAT_MEMBER_PATH, handle_unban_chat_member)

        with self.assertLogs("rooms.helpers", level=logging.WARNING) as logs:
            unban_user_in_all_chats(self.user)

        # Verify warning was logged
        self.assertTrue(any("Can't unban user" in log for log in logs.output))

        # Verify unbanChatMember was called once via HTTP (for room2)
        unban_requests = [r for r in self.server.requests_received if r.path == self.UNBAN_CHAT_MEMBER_PATH]
        self.assertEqual(len(unban_requests), 1)
