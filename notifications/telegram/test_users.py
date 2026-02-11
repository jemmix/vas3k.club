from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, call

import telegram
from django.test import TestCase

from bot.handlers.common import UserRejectReason
from notifications.telegram.common import Chat, ADMIN_CHAT
from notifications.telegram.users import (
    notify_profile_needs_review,
    notify_user_profile_approved,
    notify_user_profile_rejected,
    notify_user_ping,
    notify_admin_user_ping,
    notify_admin_user_unmoderate,
    notify_user_auth,
)
from posts.models.post import Post
from users.models.user import User


class NotificationTestBase(TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.user = User.objects.create(
            full_name="Test User",
            email="test@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        self.user_with_telegram = User.objects.create(
            full_name="Telegram User",
            email="tg@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="123456",
        )

    def tearDown(self):
        Post.objects.filter(author__in=[self.user, self.user_with_telegram]).delete()
        self.user.delete()
        self.user_with_telegram.delete()


@patch("notifications.telegram.users.send_telegram_message")
@patch("notifications.telegram.users.render_html_message", return_value="<b>review</b>")
class NotifyProfileNeedsReviewTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_admin_chat_with_reply_markup(self, mock_render, mock_send):
        intro = Post.objects.create(
            author=self.user_with_telegram,
            title="My Intro",
            text="Hello, I am a developer.",
        )
        notify_profile_needs_review(self.user_with_telegram, intro)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        self.assertEqual(kwargs["text"], "<b>review</b>")
        self.assertIsInstance(kwargs["reply_markup"], telegram.InlineKeyboardMarkup)

        mock_render.assert_called_once_with(
            "moderator_new_member_review.html",
            user=self.user_with_telegram,
            intro=intro,
        )

    async def test_reply_markup_contains_approve_and_reject_buttons(self, mock_render, mock_send):
        intro = Post.objects.create(
            author=self.user_with_telegram,
            title="My Intro",
            text="Hello.",
        )
        notify_profile_needs_review(self.user_with_telegram, intro)

        kwargs = mock_send.call_args[1]
        markup = kwargs["reply_markup"]
        # Flatten the keyboard to get all buttons
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        callback_data_values = [btn.callback_data for btn in buttons if btn.callback_data]
        self.assertIn(f"approve_user:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_intro:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_name:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_general:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_data:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_ai:{self.user_with_telegram.id}", callback_data_values)
        self.assertIn(f"reject_user_aggression:{self.user_with_telegram.id}", callback_data_values)

        # One button should be a URL button (write to user)
        url_buttons = [btn for btn in buttons if btn.url]
        self.assertEqual(len(url_buttons), 1)


@patch("notifications.telegram.users.send_telegram_message")
class NotifyUserProfileApprovedTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_user_with_telegram_id(self, mock_send):
        notify_user_profile_approved(self.user_with_telegram)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="123456"))

    async def test_skips_user_without_telegram_id(self, mock_send):
        notify_user_profile_approved(self.user)

        mock_send.assert_not_called()


@patch("notifications.telegram.users.send_telegram_message")
@patch("notifications.telegram.users.render_html_message", return_value="<b>rejected</b>")
class NotifyUserProfileRejectedTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_with_reason_template(self, mock_render, mock_send):
        notify_user_profile_rejected(self.user_with_telegram, UserRejectReason.intro)

        mock_render.assert_called_once_with("rejected/intro.html", user=self.user_with_telegram)
        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="123456"))
        self.assertEqual(kwargs["text"], "<b>rejected</b>")

    async def test_skips_user_without_telegram_id(self, mock_render, mock_send):
        notify_user_profile_rejected(self.user, UserRejectReason.intro)

        mock_send.assert_not_called()

    async def test_falls_back_to_intro_template_on_missing_template(self, mock_render, mock_send):
        from django.template import TemplateDoesNotExist

        mock_render.side_effect = [TemplateDoesNotExist("rejected/ai.html"), "<b>fallback</b>"]

        notify_user_profile_rejected(self.user_with_telegram, UserRejectReason.ai)

        self.assertEqual(mock_render.call_count, 2)
        mock_render.assert_any_call("rejected/ai.html", user=self.user_with_telegram)
        mock_render.assert_any_call("rejected/intro.html", user=self.user_with_telegram)


@patch("notifications.telegram.users.send_telegram_message")
class NotifyUserPingTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_user_with_telegram_id(self, mock_send):
        notify_user_ping(self.user_with_telegram, "Please update your profile")

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="123456"))
        self.assertIn("Please update your profile", kwargs["text"])

    async def test_skips_user_without_telegram_id(self, mock_send):
        notify_user_ping(self.user, "Please update your profile")

        mock_send.assert_not_called()


@patch("notifications.telegram.users.send_telegram_message")
class NotifyAdminUserPingTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_admin_chat(self, mock_send):
        notify_admin_user_ping(self.user, "Please update your profile")

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        self.assertIn(self.user.slug, kwargs["text"])
        self.assertIn("Please update your profile", kwargs["text"])


@patch("notifications.telegram.users.send_telegram_message")
class NotifyAdminUserUnmoderateTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_admin_chat(self, mock_send):
        notify_admin_user_unmoderate(self.user)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        self.assertIn(self.user.slug, kwargs["text"])


@patch("notifications.telegram.users.send_telegram_message")
class NotifyUserAuthTest(NotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_code_to_user_with_telegram_id(self, mock_send):
        code = MagicMock(code="123456")
        notify_user_auth(self.user_with_telegram, code)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="123456"))
        self.assertIn("123456", kwargs["text"])

    async def test_skips_user_without_telegram_id(self, mock_send):
        code = MagicMock(code="123456")
        notify_user_auth(self.user, code)

        mock_send.assert_not_called()
