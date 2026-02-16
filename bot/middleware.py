"""
Telegram bot middleware to handle database connections.

This module sets up handlers that act as hooks to trigger Django's request signals,
which automatically manage database connections through close_old_connections.
"""
import logging

from django.core.signals import request_started, request_finished
from telegram import Update
from telegram.ext import CallbackContext, TypeHandler

log = logging.getLogger(__name__)


async def request_start_handler(update: Update, context: CallbackContext) -> None:
    """
    Handler that triggers Django's request_started signal.
    Registered in group -1 to run before all other handlers.
    """
    request_started.send(sender="telegram_bot", update=update)


async def request_finish_handler(update: Update, context: CallbackContext) -> None:
    """
    Handler that triggers Django's request_finished signal.
    Registered in group 1000 to run after all other handlers.
    """
    request_finished.send(sender="telegram_bot", update=update)


def setup_middleware_handlers(application):
    """
    Register middleware handlers for database connection management.

    These handlers trigger Django's request lifecycle signals which automatically
    call close_old_connections, replacing the need for manual calls in decorators.
    """
    # Register pre-handler in group -1 (runs before all other handlers)
    application.add_handler(
        TypeHandler(Update, request_start_handler),
        group=-1
    )

    # Register post-handler in group 1000 (runs after all other handlers)
    application.add_handler(
        TypeHandler(Update, request_finish_handler),
        group=1000
    )

    log.info("Telegram bot middleware handlers registered (groups -1 and 1000)")
