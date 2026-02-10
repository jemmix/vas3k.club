from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase

from notifications.telegram.common import Chat, ADMIN_CHAT, VIBES_CHAT
from users.models.user import User


class NotifyUserBanTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(
            full_name="Test User",
            email="banuser@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="123456",
        )

    @patch("notifications.telegram.ban.send_telegram_message")
    def test_sends_message_to_user_with_telegram_id(self, mock_send_msg):
        from notifications.telegram.ban import notify_user_ban

        notify_user_ban(self.user, days=7, reason="spam")

        mock_send_msg.assert_called_once()
        call_kwargs = mock_send_msg.call_args
        self.assertEqual(call_kwargs.kwargs["chat"], Chat(id="123456"))
        self.assertIn("7 дней", call_kwargs.kwargs["text"])
        self.assertIn("spam", call_kwargs.kwargs["text"])

    @patch("notifications.telegram.ban.send_telegram_message")
    def test_skips_user_without_telegram_id(self, mock_send_msg):
        from notifications.telegram.ban import notify_user_ban

        self.user.telegram_id = None
        self.user.save()

        notify_user_ban(self.user, days=7, reason="spam")

        mock_send_msg.assert_not_called()


class NotifyAdminsOnBanTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(
            full_name="Banned User",
            email="bannedadmin@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )

    @patch("notifications.telegram.ban.send_telegram_message")
    def test_sends_to_admin_and_vibes_chats(self, mock_send_msg):
        from notifications.telegram.ban import notify_admins_on_ban

        notify_admins_on_ban(self.user, days=3, reason="toxicity")

        self.assertEqual(mock_send_msg.call_count, 2)

        chats_called = [call.kwargs["chat"] for call in mock_send_msg.call_args_list]
        self.assertIn(ADMIN_CHAT, chats_called)
        self.assertIn(VIBES_CHAT, chats_called)

        for call in mock_send_msg.call_args_list:
            text = call.kwargs["text"]
            self.assertIn(self.user.full_name, text)
            self.assertIn(self.user.slug, text)
            self.assertIn("3 дней", text)
            self.assertIn("toxicity", text)
