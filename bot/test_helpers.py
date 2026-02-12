"""
Helper functions for creating test fixtures and telegram objects in bot tests.

## Telegram Object Creation Guidelines

### Update Objects - ALWAYS use helper functions:
- create_message_update() - Regular text messages
- create_callback_query_update() - Inline keyboard callbacks
- create_command_update() - Bot commands (/start, /help, etc.)
- create_reply_update() - Messages replying to other messages
- create_forwarded_message_update() - Forwarded messages (for reply-to-forwarded patterns)

Why use helpers instead of MagicMock()?
- Validates telegram library API usage
- Catches breaking changes in telegram library
- Provides real object behavior (properties, methods)
- Enables IDE autocomplete and type checking

### CallbackContext Objects - Use MagicMock(spec=CallbackContext):
```python
from unittest.mock import MagicMock
from telegram.ext import CallbackContext

context = MagicMock(spec=CallbackContext)
context.bot = self.bot
context.user_data = {}  # MUST be real dict if handler uses it!
```

Why MagicMock instead of real CallbackContext?
- Real CallbackContext requires full Dispatcher initialization (complex)
- Handlers only access context.bot (no advanced features)
- MagicMock(spec=...) validates attribute names without complexity
- This is telegram library's recommended approach for unit tests

### Critical: context.user_data must be a real dict
Handlers perform dictionary operations (key access, 'in' checks, .clear()).
MagicMock won't support these correctly - always use real dict: {}
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import telegram
from telegram import Update, Message, User as TgUser, Chat as TgChat, CallbackQuery, MessageEntity

from users.models.user import User


# Response constants for mock HTTP server
def SEND_MESSAGE_RESPONSE(chat_id: int = 12345, message_id: int = 123456):
    """Generate a standard sendMessage API response."""
    return json.dumps({
        "ok": True,
        "result": {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {
                "id": chat_id,
                "type": "private",
            },
        },
    })


def ANSWER_CALLBACK_QUERY_RESPONSE():
    """Generate a standard answerCallbackQuery API response."""
    return json.dumps({"ok": True, "result": True})


def EDIT_MESSAGE_REPLY_MARKUP_RESPONSE(message_id: int = 123456):
    """Generate a standard editMessageReplyMarkup API response."""
    return json.dumps({
        "ok": True,
        "result": {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {"id": 12345, "type": "private"},
            "text": "Message text",
        },
    })


def DELETE_MESSAGE_RESPONSE():
    """Generate a standard deleteMessage API response."""
    return json.dumps({"ok": True, "result": True})


def GET_CHAT_MEMBER_RESPONSE(user_id: int, status: str = "member"):
    """Generate a standard getChatMember API response."""
    return json.dumps({
        "ok": True,
        "result": {
            "user": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
            },
            "status": status,
        },
    })


def SEND_CHAT_ACTION_RESPONSE():
    """Generate a standard sendChatAction API response."""
    return json.dumps({"ok": True, "result": True})


def create_test_user(**overrides) -> User:
    """
    Factory for creating a test User with active membership defaults.

    Usage:
        user = create_test_user()
        user = create_test_user(telegram_id="999", slug="custom-slug")
    """
    now = datetime.now(timezone.utc)
    # Use UUID to ensure uniqueness even when tests run in parallel
    unique_id = uuid.uuid4().hex[:12]
    defaults = {
        "slug": f"testuser-{unique_id}",
        "email": f"test-{unique_id}@example.com",
        "full_name": "Test User",
        "secret_hash": f"secret_{unique_id}",
        "membership_started_at": now,
        "membership_expires_at": now + timedelta(days=30),
        "moderation_status": User.MODERATION_STATUS_APPROVED,
    }
    defaults.update(overrides)
    return User.objects.create(**defaults)


def create_message_update(
    bot: telegram.Bot,
    telegram_id: int,
    chat_id: int,
    text: str,
    message_id: int = 1,
    reply_to_message: Optional[Message] = None,
    entities: Optional[list] = None,
) -> Update:
    """
    Build a real telegram.Update with a Message.

    Args:
        bot: The telegram.Bot instance (from BaseTelegramTest.bot)
        telegram_id: Telegram user ID
        chat_id: Telegram chat ID (use negative values for groups: -1001234567890)
        text: Message text
        message_id: Message ID (default 1)
        reply_to_message: Optional Message being replied to
        entities: Optional list of MessageEntity objects

    Returns:
        telegram.Update with a Message
    """
    # Create message using de_json to properly handle reply_to_message and entities
    chat_type = "supergroup" if str(chat_id).startswith("-100") else "private"

    message_dict = {
        "message_id": message_id,
        "date": int(time.time()),
        "chat": {
            "id": chat_id,
            "type": chat_type
        },
        "from": {
            "id": telegram_id,
            "is_bot": False,
            "first_name": "Test"
        },
        "text": text,
    }

    if reply_to_message:
        message_dict["reply_to_message"] = reply_to_message.to_dict()

    if entities:
        message_dict["entities"] = [e.to_dict() if hasattr(e, 'to_dict') else e for e in entities]

    message = Message.de_json(message_dict, bot)

    return Update(update_id=1, message=message)


def create_callback_query_update(
    bot: telegram.Bot,
    telegram_id: int,
    chat_id: int,
    data: str,
    message_text: str = "Original message",
    message_id: int = 100,
) -> Update:
    """
    Build a real telegram.Update with a CallbackQuery.

    Args:
        bot: The telegram.Bot instance
        telegram_id: Telegram user ID
        chat_id: Telegram chat ID
        data: Callback data (e.g., "upvote_post:123")
        message_text: Text of the message with inline keyboard
        message_id: Message ID

    Returns:
        telegram.Update with a CallbackQuery
    """
    # Use de_json to create CallbackQuery since direct construction has issues
    callback_query_dict = {
        "id": "callback_query_id",
        "from": {
            "id": telegram_id,
            "is_bot": False,
            "first_name": "Test",
        },
        "chat_instance": "chat_instance",
        "data": data,
        "message": {
            "message_id": message_id,
            "date": int(time.time()),
            "chat": {
                "id": chat_id,
                "type": "private",
            },
            "text": message_text,
        },
    }
    callback_query = CallbackQuery.de_json(callback_query_dict, bot)

    return Update(update_id=1, callback_query=callback_query)


def create_command_update(
    bot: telegram.Bot,
    telegram_id: int,
    chat_id: int,
    command: str,
    args: str = "",
) -> Update:
    """
    Build a telegram.Update with a command (e.g., /auth secret123).

    Args:
        bot: The telegram.Bot instance
        telegram_id: Telegram user ID
        chat_id: Telegram chat ID
        command: Command name (e.g., "auth", "whois")
        args: Command arguments

    Returns:
        telegram.Update with a Message containing a bot_command entity
    """
    text = f"/{command}"
    if args:
        text += f" {args}"

    entity = MessageEntity(
        type="bot_command",
        offset=0,
        length=len(f"/{command}"),
    )

    tg_user = TgUser(id=telegram_id, is_bot=False, first_name="Test")
    tg_chat = TgChat(id=chat_id, type="private")
    tg_chat.set_bot(bot)

    message = Message(
        message_id=1,
        date=int(time.time()),
        chat=tg_chat,
        from_user=tg_user,
        text=text,
        entities=[entity],
    )
    message.set_bot(bot)

    return Update(update_id=1, message=message)


def create_reply_update(
    bot: telegram.Bot,
    telegram_id: int,
    chat_id: int,
    text: str,
    reply_to_text: str,
    reply_to_user_id: int = 6789,
    reply_to_message_id: int = 100,
    reply_to_entities: Optional[list] = None,
) -> Update:
    """
    Build a telegram.Update where the message is replying to another message.

    Args:
        bot: The telegram.Bot instance
        telegram_id: Telegram user ID sending the reply
        chat_id: Telegram chat ID (use negative values for groups: -1001234567890)
        text: Reply text
        reply_to_text: Text of the message being replied to
        reply_to_user_id: User ID of the original message author
        reply_to_message_id: Message ID being replied to
        reply_to_entities: Optional entities in the replied-to message

    Returns:
        telegram.Update with a Message that has reply_to_message set
    """
    # Create reply_to_message using de_json to properly handle entities
    chat_type = "supergroup" if str(chat_id).startswith("-100") else "private"

    reply_to_dict = {
        "message_id": reply_to_message_id,
        "date": int(time.time()) - 100,
        "chat": {
            "id": chat_id,
            "type": chat_type
        },
        "from": {
            "id": reply_to_user_id,
            "is_bot": False,
            "first_name": "ReplyUser"
        },
        "text": reply_to_text,
    }

    if reply_to_entities:
        reply_to_dict["entities"] = [e.to_dict() if hasattr(e, 'to_dict') else e for e in reply_to_entities]

    reply_to_message = Message.de_json(reply_to_dict, bot)

    return create_message_update(
        bot=bot,
        telegram_id=telegram_id,
        chat_id=chat_id,
        text=text,
        reply_to_message=reply_to_message,
    )


def create_forwarded_message_update(
    bot: telegram.Bot,
    telegram_id: int,
    chat_id: int,
    text: str,
    forward_from_chat_id: int,
    forward_from_message_id: int,
    message_id: int = 1,
) -> Update:
    """
    Build a telegram.Update with a Message that is replying to a forwarded message.

    This is used in helpdeskbot where users reply to forwarded questions from channels.
    The reply_to_message will have forward_from_chat and forward_from_message_id set.

    Args:
        bot: The telegram.Bot instance
        telegram_id: Telegram user ID sending the reply
        chat_id: Telegram chat ID (use negative values for groups: -1001234567890)
        text: Reply text
        forward_from_chat_id: Channel/chat ID that the original message was forwarded from
        forward_from_message_id: Original message ID in the forwarded-from channel
        message_id: Message ID (default 1)

    Returns:
        telegram.Update with a Message replying to a forwarded message

    Example:
        # User replies to a question forwarded from a channel
        update = create_forwarded_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-1001234567890,
            text="This is the answer",
            forward_from_chat_id=-1001234567890,
            forward_from_message_id=12345,
        )
        # update.message.reply_to_message.forward_from_message_id == 12345
        # update.message.reply_to_message.forward_from_chat.id == -1001234567890
    """
    tg_user = TgUser(id=telegram_id, is_bot=False, first_name="Test")
    tg_chat = TgChat(id=chat_id, type="supergroup" if str(chat_id).startswith("-100") else "private")
    tg_chat.set_bot(bot)

    # Create the forwarded-from chat
    forward_from_chat = TgChat(
        id=forward_from_chat_id,
        type="channel" if str(forward_from_chat_id).startswith("-100") else "private",
    )
    forward_from_chat.set_bot(bot)

    # Create the forwarded message (the one being replied to) using de_json
    # with v20+ forward_origin structure
    forward_date = int(time.time()) - 200
    forwarded_message_dict = {
        "message_id": forward_from_message_id,
        "date": forward_date,
        "chat": {
            "id": chat_id,
            "type": "supergroup" if str(chat_id).startswith("-100") else "private"
        },
        "from": {
            "id": 999,
            "is_bot": False,
            "first_name": "OriginalAuthor"
        },
        "text": "[Forwarded question]",
        "forward_origin": {
            "type": "channel",
            "date": forward_date,
            "chat": {
                "id": forward_from_chat_id,
                "type": "channel" if str(forward_from_chat_id).startswith("-100") else "private"
            },
            "message_id": forward_from_message_id,
        }
    }
    forwarded_message = Message.de_json(forwarded_message_dict, bot)

    # Create the reply message
    reply_message = Message(
        message_id=message_id,
        date=int(time.time()),
        chat=tg_chat,
        from_user=tg_user,
        text=text,
        reply_to_message=forwarded_message,
    )
    reply_message.set_bot(bot)

    return Update(update_id=1, message=reply_message)
