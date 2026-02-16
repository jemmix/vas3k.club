from notifications.telegram.common import send_telegram_message_async, VIBES_CHAT, ADMIN_CHAT, render_html_message


async def notify_moderators_on_mention(comment):
    for chat in [ADMIN_CHAT, VIBES_CHAT]:
        await send_telegram_message_async(
            chat=chat,
            text=render_html_message("moderator_mention.html", comment=comment),
        )
