from django.conf import settings
from django.urls import reverse

from notifications.telegram.common import send_telegram_image_async, render_html_message, send_telegram_message_async, Chat, \
    VIBES_CHAT
from users.models.achievements import UserAchievement
from users.models.user import User


async def notify_user_new_achievement(user_achievement: UserAchievement):
    if user_achievement.user.is_member and user_achievement.user.telegram_id:
        if user_achievement.achievement.image:
            await send_telegram_image_async(
                chat=Chat(id=user_achievement.user.telegram_id),
                image_url=user_achievement.achievement.image,
                text=render_html_message(
                    "achievement.html",
                    user=user_achievement.user,
                    achievement=user_achievement.achievement
                ),
            )

        if user_achievement.achievement.custom_message:
            await send_telegram_message_async(
                chat=Chat(id=user_achievement.user.telegram_id),
                text=user_achievement.achievement.custom_message,
            )


async def notify_admins_on_achievement(user_achievement: UserAchievement, from_user: User | None = None):
    user_profile_url = settings.APP_HOST + reverse("profile", kwargs={"user_slug": user_achievement.user.slug})
    text = f"🏆 Юзеру <b><a href=\"{user_profile_url}\">{user_achievement.user.full_name}</a></b> " \
        f"дали ачивку «{user_achievement.achievement.name} (выдал: {from_user.full_name if from_user else None})»"

    if VIBES_CHAT is not None:
        await send_telegram_message_async(chat=VIBES_CHAT, text=text)
