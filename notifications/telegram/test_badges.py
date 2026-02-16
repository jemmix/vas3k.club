from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.test import TestCase

from badges.models import Badge, UserBadge
from notifications.telegram.common import Chat
from users.models.user import User


class SendNewBadgeMessageTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        self.member_user = User.objects.create(
            full_name="Badge Recipient",
            email="badge_recipient@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="99999",
        )
        self.badge = Badge.objects.create(
            code="testbadge",
            title="Test Badge",
        )
        self.user_badge = UserBadge.objects.create(
            badge=self.badge,
            to_user=self.member_user,
        )

    @patch("notifications.telegram.badges.render_html_message")
    @patch("notifications.telegram.badges.send_telegram_image_async")
    async def test_sends_image_to_user_with_telegram_id(self, mock_send_img, mock_render):
        from notifications.telegram.badges import send_new_badge_message

        mock_render.return_value = "<b>You got a badge!</b>"

        await send_new_badge_message(self.user_badge)

        mock_send_img.assert_called_once()
        call_kwargs = mock_send_img.call_args
        self.assertEqual(call_kwargs.kwargs["chat"], Chat(id="99999"))
        self.assertIn("testbadge.png", call_kwargs.kwargs["image_url"])
        self.assertEqual(call_kwargs.kwargs["text"], "<b>You got a badge!</b>")

    @patch("notifications.telegram.badges.render_html_message")
    @patch("notifications.telegram.badges.send_telegram_image_async")
    async def test_skips_non_member_user(self, mock_send_img, mock_render):
        from notifications.telegram.badges import send_new_badge_message
        from badges.models import UserBadge

        self.member_user.moderation_status = User.MODERATION_STATUS_INTRO
        await self.member_user.asave()

        # Refetch user_badge with updated to_user
        user_badge = await UserBadge.objects.select_related("to_user").aget(id=self.user_badge.id)

        await send_new_badge_message(user_badge)

        mock_send_img.assert_not_called()

    @patch("notifications.telegram.badges.render_html_message")
    @patch("notifications.telegram.badges.send_telegram_image_async")
    async def test_skips_user_without_telegram_id(self, mock_send_img, mock_render):
        from notifications.telegram.badges import send_new_badge_message
        from badges.models import UserBadge

        self.member_user.telegram_id = None
        await self.member_user.asave()

        # Refetch user_badge with updated to_user
        user_badge = await UserBadge.objects.select_related("to_user").aget(id=self.user_badge.id)

        await send_new_badge_message(user_badge)

        mock_send_img.assert_not_called()
