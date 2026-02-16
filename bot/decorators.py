from django.conf import settings
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from bot.cache import cached_telegram_users
from users.models.user import User


def is_moderator(callback):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if update.effective_chat.id != int(settings.TELEGRAM_ADMIN_CHAT_ID):
            await update.effective_chat.send_message("❌ Для этого действия нужно быть в чате модераторов")
            return None

        # Use Django's native async ORM (available in Django 4.1+)
        moderator = await User.objects.filter(telegram_id=update.effective_user.id).afirst()
        if not moderator or not moderator.is_moderator:
            await update.effective_chat.send_message(
                f"⚠️ '{update.effective_user.full_name}' не модератор или не привязал бота к аккаунту"
            )
            return None

        return await callback(update, context, *args, **kwargs)

    return wrapper


def is_club_member(callback):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        club_users = cached_telegram_users()

        if str(update.effective_user.id) not in set(club_users):
            if update.callback_query:
                await update.callback_query.answer(text=f"☝️ Привяжи бота к профилю, братишка")
            else:
                await update.message.reply_text(
                    f"☝️ Привяжи <a href=\"https://vas3k.club/user/me/edit/bot/\">бота</a> к профилю, братишка",
                    parse_mode=ParseMode.HTML
                )
            return None

        return await callback(update, context, *args, **kwargs)

    return wrapper
