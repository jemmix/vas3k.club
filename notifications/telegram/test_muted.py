from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase

from notifications.telegram.common import ADMIN_CHAT, VIBES_CHAT
from users.models.user import User


class NotifyAdminsOnMuteTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        self.user_from = User.objects.create(
            full_name="Muter User",
            email="muter@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        self.user_to = User.objects.create(
            full_name="Muted User",
            email="muted@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )

    @patch("notifications.telegram.muted.send_telegram_message")
    async def test_sends_to_admin_and_vibes_chats(self, mock_send_msg):
        from notifications.telegram.muted import notify_admins_on_mute

        notify_admins_on_mute(self.user_from, self.user_to, comment="rude behavior")

        self.assertEqual(mock_send_msg.call_count, 2)

        chats_called = [call.kwargs["chat"] for call in mock_send_msg.call_args_list]
        self.assertIn(ADMIN_CHAT, chats_called)
        self.assertIn(VIBES_CHAT, chats_called)

    @patch("notifications.telegram.muted.send_telegram_message")
    async def test_text_contains_user_names(self, mock_send_msg):
        from notifications.telegram.muted import notify_admins_on_mute

        notify_admins_on_mute(self.user_from, self.user_to, comment="being mean")

        for call in mock_send_msg.call_args_list:
            text = call.kwargs["text"]
            self.assertIn(self.user_from.full_name, text)
            self.assertIn(self.user_to.full_name, text)
