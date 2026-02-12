import logging

from asgiref.sync import sync_to_async
from django.urls import reverse
from telegram import Update
from telegram.ext import CallbackContext

from bot.handlers.common import get_club_user
from club import settings
from posts.models.post import Post
from posts.models.subscriptions import PostSubscription

log = logging.getLogger(__name__)


async def subscribe(update: Update, context: CallbackContext) -> None:
    user = await get_club_user(update)
    if not user or not user.telegram_id:
        return None

    _, post_id = update.callback_query.data.split(":", 1)
    post = await Post.objects.filter(id=post_id).afirst()
    if not post:
        return None

    _, is_created = await sync_to_async(PostSubscription.subscribe)(
        user=user,
        post=post,
        type=PostSubscription.TYPE_TOP_LEVEL_ONLY,
    )

    if user.telegram_id:
        await update.callback_query.answer(
            text=f"Вы подписались на уведомления о новых комментариях к посту «{post.title}» 🔔"
        )


async def unsubscribe(update: Update, context: CallbackContext) -> None:
    user = await get_club_user(update)
    if not user or not user.telegram_id:
        return None

    _, post_id = update.callback_query.data.split(":", 1)
    post = await Post.objects.filter(id=post_id).afirst()
    if not post:
        return None

    deleted_count, _ = await sync_to_async(PostSubscription.unsubscribe)(
        user=user,
        post=post,
    )

    if user.telegram_id:
        post_url = settings.APP_HOST + reverse("show_post", kwargs={
            "post_type": post.type,
            "post_slug": post.slug,
        })

        if deleted_count > 0:
            await update.callback_query.answer(
                text=f"Вы отписались от комментариев к посту «{post.title}» 🔕"
            )
        else:
            await update.callback_query.answer(
                text="Вы и не были подписаны на уведомления к этому посту ❌"
            )
