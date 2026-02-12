from django.urls import reverse
from telegram import Update
from telegram import Chat as TGChat
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from bot.decorators import is_club_member, ensure_fresh_db_connection
from club import settings
from users.models.user import User


@is_club_member
@ensure_fresh_db_connection
async def command_whois(update: Update, context: CallbackContext) -> None:
    # In v20+, forward info is in forward_origin
    is_private_forward = update.message is not None \
        and update.message.forward_origin is not None \
        and update.message.chat.type == TGChat.PRIVATE

    if not update.message or not update.message.reply_to_message and not is_private_forward:
        await update.effective_chat.send_message(
            "Эту команду нужно вызывать реплаем на сообщение человека, о котором вы хотите узнать",
        )
        return None

    original_message = update.message  # look at the author of this message (works only in private chats)
    if update.message.reply_to_message:
        original_message = update.message.reply_to_message  # look at the author of replied message

    from_user = original_message.from_user
    if original_message.forward_origin:
        # Check if it's a user forward (not channel/hidden)
        from telegram import MessageOriginUser, MessageOriginHiddenUser
        if isinstance(original_message.forward_origin, MessageOriginHiddenUser):
            await update.effective_chat.send_message(
                f"🤨 Кажется, {original_message.forward_origin.sender_user_name} скрыл свой профиль для пересылаемых сообщений. Попробуй дать команду в ответ на исходное сообщение",
                )
            return None
        elif isinstance(original_message.forward_origin, MessageOriginUser):
            from_user = original_message.forward_origin.sender_user

    if from_user.is_bot:
        if getattr(original_message, 'sender_chat', None):
            await update.message.reply_text(
                "Сообщение отправлено от имени чата/канала",
                )
            return
        await update.message.reply_text(
            "Это бот, глупышка",
        )
        return None

    telegram_id = from_user.id
    user = await User.objects.filter(telegram_id=telegram_id).afirst()
    if not user:
        await update.message.reply_text(
            f"🤨 Пользователь не найден в Клубе. Гоните его, насмехайтесь над ним!",
        )
        return None

    profile_url = settings.APP_HOST + reverse("profile", kwargs={
        "user_slug": user.slug,
    })

    await update.message.reply_text(
        f"""Кажется, это <a href="{profile_url}">{user.full_name}</a>""",
        parse_mode=ParseMode.HTML,
        quote=True
    )

    return None
