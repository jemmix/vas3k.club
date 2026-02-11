import asyncio
import logging
import os
import sys
import django
from dataclasses import dataclass

# IMPORTANT: this should go before any django-related imports (models, apps, settings)
# These lines must be kept together till THE END
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "club.settings")
django.setup()
# THE END

from django.conf import settings
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters, \
    CallbackQueryHandler

from bot.cache import cached_telegram_users
from bot.config import WELCOME_MESSAGE, BOT_MENTION_RE, ANONYMOUS_MESSAGE
from bot.handlers import moderation, comments, upvotes, auth, whois, fun, top, posts, llm

log = logging.getLogger(__name__)


async def command_help(update: Update, context: CallbackContext) -> None:
    await update.effective_chat.send_message(
        WELCOME_MESSAGE,
        parse_mode=ParseMode.HTML
    )


async def private_message(update: Update, context: CallbackContext) -> None:
    log.info("Private message handler triggered")

    club_users = cached_telegram_users()
    if str(update.effective_user.id) not in set(club_users):
        await update.effective_chat.send_message(
            ANONYMOUS_MESSAGE,
            parse_mode=ParseMode.HTML
        )
    else:
        return await llm.llm_response(update, context)


@dataclass
class Server:
    application: Application

    async def run_blocking(self):
        async with self.application:
            await self.application.start()
            await self.application.updater.start_polling()
            await asyncio.Event().wait()  # Run forever

    async def start_webhook(self, host: str, port: int, url_path: str):
        """Start the application and webhook server for testing"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_webhook(
            listen=host,
            port=port,
            url_path=url_path,
        )
        # Keep the event loop alive while webhook server runs
        await asyncio.Event().wait()

    async def stop(self):
        if self.application.updater and self.application.updater.running:
            await self.application.updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()


def start_server() -> Server:
    # Allow optional TELEGRAM_BASE_URL override for testing with mock servers
    builder = Application.builder().token(settings.TELEGRAM_TOKEN)

    # Add base_url if provided (for testing with mock servers)
    base_url = getattr(settings, 'TELEGRAM_BASE_URL', None)
    if base_url:
        builder = builder.base_url(base_url)

    application = builder.build()

    # Admin callbacks
    application.add_handler(CallbackQueryHandler(moderation.approve_post, pattern=r"^approve_post:.+"))
    application.add_handler(CallbackQueryHandler(moderation.forgive_post, pattern=r"^forgive_post:.+"))
    application.add_handler(CallbackQueryHandler(moderation.reject_post, pattern=r"^reject_post.+"))
    application.add_handler(CallbackQueryHandler(moderation.approve_user_profile, pattern=r"^approve_user:.+"))
    application.add_handler(CallbackQueryHandler(moderation.reject_user_profile, pattern=r"^reject_user.+"))

    # Commands and buttons
    application.add_handler(CommandHandler("help", command_help))
    application.add_handler(CommandHandler("horo", fun.command_horo))
    application.add_handler(CommandHandler("random", fun.command_random))
    application.add_handler(CommandHandler("top", top.command_top))
    application.add_handler(CommandHandler("whois", whois.command_whois))
    application.add_handler(CallbackQueryHandler(posts.subscribe, pattern=r"^subscribe:.+"))
    application.add_handler(CallbackQueryHandler(posts.unsubscribe, pattern=r"^unsubscribe:.+"))
    application.add_handler(CallbackQueryHandler(upvotes.upvote_post, pattern=r"^upvote_post:.+"))
    application.add_handler(CallbackQueryHandler(upvotes.upvote_comment, pattern=r"^upvote_comment:.+"))
    application.add_handler(
        MessageHandler(filters.REPLY & filters.Regex(r"^\+[+\d ]*$"), upvotes.upvote)
    )

    # AI
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(BOT_MENTION_RE), llm.llm_response)
    )

    # Handle comments to posts and replies
    application.add_handler(
        MessageHandler(filters.REPLY & ~filters.Chat(int(settings.TELEGRAM_ADMIN_CHAT_ID)), comments.comment)
    )

    # Private chat with bot
    application.add_handler(CommandHandler("start", auth.command_auth, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("auth", auth.command_auth, filters.ChatType.PRIVATE))
    application.add_handler(MessageHandler(filters.FORWARDED & filters.ChatType.PRIVATE, whois.command_whois))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE, private_message))

    return Server(application=application)


async def main() -> None:
    await start_server().run_blocking()


if __name__ == '__main__':
    asyncio.run(main())
