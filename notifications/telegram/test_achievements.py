from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

from django.test import TestCase

from notifications.telegram.achievements import notify_user_new_achievement, notify_admins_on_achievement
from notifications.telegram.common import Chat, VIBES_CHAT
from users.models.achievements import Achievement, UserAchievement
from users.models.user import User


async def _create_user(telegram_id=None, moderation_status=User.MODERATION_STATUS_APPROVED, **kwargs):
    defaults = dict(
        full_name="Test User",
        email=f"test_{datetime.utcnow().timestamp()}@example.com",
        membership_started_at=datetime.utcnow() - timedelta(days=30),
        membership_expires_at=datetime.utcnow() + timedelta(days=30),
        moderation_status=moderation_status,
        telegram_id=telegram_id,
    )
    defaults.update(kwargs)
    return await User.objects.acreate(**defaults)


async def _create_achievement(code, image="https://example.com/badge.png", custom_message=None):
    return await Achievement.objects.acreate(
        code=code,
        name=f"Achievement {code}",
        image=image,
        description=f"Description for {code}",
        custom_message=custom_message,
    )


class NotifyUserNewAchievementTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    @patch("notifications.telegram.achievements.render_html_message", return_value="<b>rendered</b>")
    @patch("notifications.telegram.achievements.send_telegram_image_async")
    async def test_sends_image_when_achievement_has_image(self, mock_send_image, mock_render):
        user = await _create_user(telegram_id="123456")
        achievement = await _create_achievement(code="img_test")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_user_new_achievement(user_achievement)

        mock_send_image.assert_called_once_with(
            chat=Chat(id="123456"),
            image_url=achievement.image,
            text="<b>rendered</b>",
        )
        mock_render.assert_called_once_with(
            "achievement.html",
            user=user,
            achievement=achievement,
        )

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    @patch("notifications.telegram.achievements.send_telegram_image_async")
    async def test_sends_custom_message_when_present(self, mock_send_image, mock_send_message):
        user = await _create_user(telegram_id="123456")
        achievement = await _create_achievement(code="msg_test", image="", custom_message="Congrats!")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_user_new_achievement(user_achievement)

        mock_send_image.assert_not_called()
        mock_send_message.assert_called_once_with(
            chat=Chat(id="123456"),
            text="Congrats!",
        )

    @patch("notifications.telegram.achievements.render_html_message", return_value="<b>rendered</b>")
    @patch("notifications.telegram.achievements.send_telegram_message_async")
    @patch("notifications.telegram.achievements.send_telegram_image_async")
    async def test_sends_both_image_and_custom_message(self, mock_send_image, mock_send_message, mock_render):
        user = await _create_user(telegram_id="123456")
        achievement = await _create_achievement(code="both_test", custom_message="Well done!")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_user_new_achievement(user_achievement)

        mock_send_image.assert_called_once_with(
            chat=Chat(id="123456"),
            image_url=achievement.image,
            text="<b>rendered</b>",
        )
        mock_send_message.assert_called_once_with(
            chat=Chat(id="123456"),
            text="Well done!",
        )

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    @patch("notifications.telegram.achievements.send_telegram_image_async")
    async def test_skips_non_member(self, mock_send_image, mock_send_message):
        user = await _create_user(telegram_id="123456", moderation_status=User.MODERATION_STATUS_INTRO)
        achievement = await _create_achievement(code="skip_nonmember", custom_message="Hello")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_user_new_achievement(user_achievement)

        mock_send_image.assert_not_called()
        mock_send_message.assert_not_called()

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    @patch("notifications.telegram.achievements.send_telegram_image_async")
    async def test_skips_user_without_telegram_id(self, mock_send_image, mock_send_message):
        user = await _create_user(telegram_id=None)
        achievement = await _create_achievement(code="skip_notg", custom_message="Hello")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_user_new_achievement(user_achievement)

        mock_send_image.assert_not_called()
        mock_send_message.assert_not_called()


class NotifyAdminsOnAchievementTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    async def test_sends_to_vibes_chat(self, mock_send_message):
        user = await _create_user(telegram_id="123456")
        achievement = await _create_achievement(code="admin_test")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_admins_on_achievement(user_achievement)

        mock_send_message.assert_called_once()
        call_kwargs = mock_send_message.call_args
        self.assertEqual(call_kwargs.kwargs["chat"], VIBES_CHAT)
        self.assertIn(user.full_name, call_kwargs.kwargs["text"])
        self.assertIn(achievement.name, call_kwargs.kwargs["text"])

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    async def test_includes_from_user_when_provided(self, mock_send_message):
        user = await _create_user(telegram_id="123456")
        from_user = await _create_user(
            telegram_id="654321",
            email="admin@example.com",
            full_name="Admin User",
        )
        achievement = await _create_achievement(code="from_user_test")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_admins_on_achievement(user_achievement, from_user=from_user)

        call_kwargs = mock_send_message.call_args
        self.assertIn("Admin User", call_kwargs.kwargs["text"])

    @patch("notifications.telegram.achievements.send_telegram_message_async")
    async def test_handles_no_from_user(self, mock_send_message):
        user = await _create_user(telegram_id="123456")
        achievement = await _create_achievement(code="no_from_test")
        user_achievement = await UserAchievement.objects.acreate(user=user, achievement=achievement)

        await notify_admins_on_achievement(user_achievement, from_user=None)

        mock_send_message.assert_called_once()
        call_kwargs = mock_send_message.call_args
        self.assertIn("None", call_kwargs.kwargs["text"])
