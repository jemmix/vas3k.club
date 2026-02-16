import logging
from enum import Enum
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode

from bot.config import COMMENT_URL_RE, POST_URL_RE
from comments.models import Comment
from posts.models.post import Post
from users.models.user import User

log = logging.getLogger(__name__)


class UserRejectReason(Enum):
    intro = "intro"
    data = "data"
    ai = "ai"
    aggression = "aggression"
    general = "general"
    name = "name"


class PostRejectReason(Enum):
    title = "title"
    design = "design"
    dyor = "dyor"
    duplicate = "duplicate"
    chat = "chat"
    tldr = "tldr"
    github = "github"
    bias = "bias"
    hot = "hot"
    ad = "ad"
    inside = "inside"
    value = "value"
    draft = "draft"
    false_dilemma = "false_dilemma"


async def get_club_user(update: Update):
    # Use Django's native async ORM (available in Django 4.1+)
    user = await User.objects.filter(telegram_id=update.effective_user.id).afirst()
    if not user:
        if update.callback_query:
            await update.callback_query.answer(text=f"☝️ Привяжи бота к профилю, братишка")
        else:
            await update.message.reply_text(
                f"😐 Привяжи <a href=\"https://vas3k.club/user/me/edit/bot/\">бота</a> к профилю, братишка",
                parse_mode=ParseMode.HTML
            )
        return None

    if user.is_banned:
        if update.callback_query:
            await update.callback_query.answer(text=f"🙈 Ты в бане, мы больше не дружим")
        else:
            await update.message.reply_text(f"🙈 Ты в бане, мы больше не дружим")
        return None

    if not user.is_member:
        if update.callback_query:
            await update.callback_query.answer(text=f"😣 Твой профиль в Клубе неактивен. Плоти долор!")
        else:
            await update.message.reply_text(f"😣 Твой профиль в Клубе неактивен. Плоти долор!")
        return None

    return user


async def get_club_comment(update: Update) -> Optional[Comment]:
    entities = update.message.reply_to_message.entities or update.message.reply_to_message.caption_entities or []
    url_entities = [
        entity["url"] for entity in entities if entity["type"] == "text_link"
    ]

    for url_entity in url_entities:
        match = COMMENT_URL_RE.match(url_entity)
        if match:
            comment_id = match.group(1)
            if comment_id:
                break
    else:
        log.warning(f"Comment URL not found in message: {update.message.reply_to_message}")
        return None

    # Use Django's native async ORM
    comment = await Comment.objects.filter(id=comment_id).select_related("post", "author", "reply_to").afirst()
    if not comment:
        await update.message.reply_text(f"🤨 Коммент '{comment_id}' был удален или куда-то делся")
        return None

    return comment


async def get_club_post(update: Update) -> Optional[Post]:
    entities = update.message.reply_to_message.entities or update.message.reply_to_message.caption_entities or []
    url_entities = [
        entity["url"] for entity in entities if entity["type"] == "text_link"
    ]

    for url_entity in url_entities:
        match = POST_URL_RE.match(url_entity)
        if match:
            post_id = match.group(1)
            if post_id:
                break
    else:
        log.warning(f"Post URL not found in message: {update.message.reply_to_message}")
        return None

    # Use Django's native async ORM
    post = await Post.objects.filter(slug=post_id).afirst()
    if not post or not post.is_commentable:
        await update.message.reply_text(f"🤨 Пост был удален, скрыт или украден, сорян")
        return None

    return post
