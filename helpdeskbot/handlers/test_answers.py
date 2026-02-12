"""Tests for helpdeskbot/handlers/answers.py"""

from unittest.mock import patch, MagicMock, AsyncMock

from django.test import TestCase
from telegram.ext import CallbackContext

from bot.test_helpers import (
    create_test_user,
    create_message_update,
    create_reply_update,
    create_forwarded_message_update,
)
from helpdeskbot.models import Question, Answer
from helpdeskbot.room import Room
from notifications.telegram.tests import BaseTelegramTest

# Import handlers after patching token
with patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"):
    from helpdeskbot.handlers.answers import (
        on_reply_message,
        handle_answer_from_channel,
        handle_answer_from_room_chat,
        notify_user_about_answer,
    )


@patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
class AnswersTestBase(BaseTelegramTest, TestCase):
    """Base class with token patch and bot setup for all answer handler tests"""
    tags = {"telegram", "telegram_helpdesk"}


class HandleAnswerFromChannelTest(AnswersTestBase):
    """Test handle_answer_from_channel function"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="questioner@example.com", telegram_id="111")

        # Create a question
        self.question = Question.objects.create(
            user=self.user,
            channel_msg_id=12345,
            json_text={"title": "Test Question", "body": "Question body"},
        )

    def tearDown(self):
        Question.objects.filter(id=self.question.id).delete()
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.answers.notify_user_about_answer", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.answers.Answer.create_from_update")
    async def test_creates_answer_and_notifies_user(self, mock_create_answer, mock_notify):
        """Should create answer from update and notify user"""
        # Create update where user replies to a forwarded question from channel
        update = create_forwarded_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-1001234567890,
            text="This is the answer",
            forward_from_chat_id=-1001234567890,
            forward_from_message_id=12345
        )

        await handle_answer_from_channel(update)

        # Verify answer was created
        mock_create_answer.assert_called_once()
        question_arg = mock_create_answer.call_args[0][0]
        self.assertEqual(question_arg.id, self.question.id)

        # Verify user was notified
        mock_notify.assert_called_once()

    @patch("helpdeskbot.handlers.answers.log")
    async def test_handles_missing_forward_message_id(self, mock_log):
        """Should log error when forward_origin is missing"""
        # Create a reply update without forward metadata (no forward_origin)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-1001234567890,
            text="Answer",
            reply_to_text="Question"
        )
        # reply_to_message won't have forward_origin by default

        result = await handle_answer_from_channel(update)

        self.assertIsNone(result)
        mock_log.error.assert_called_once()

    @patch("helpdeskbot.handlers.answers.log")
    async def test_handles_question_not_found(self, mock_log):
        """Should log warning when question is not found"""
        # Create update with non-existent forward_from_message_id
        update = create_forwarded_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-1001234567890,
            text="Answer",
            forward_from_chat_id=-1001234567890,
            forward_from_message_id=99999  # Non-existent
        )

        result = await handle_answer_from_channel(update)

        self.assertIsNone(result)
        mock_log.warning.assert_called_once()


class HandleAnswerFromRoomChatTest(AnswersTestBase):
    """Test handle_answer_from_room_chat function"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="questioner@example.com", telegram_id="111")

        # Create a mock room
        self.room = Room(
            slug="test-room",
            title="Test Room",
            chat_id="-100123456789",
        )

        # Create a question with room
        self.question = Question.objects.create(
            user=self.user,
            channel_msg_id=12345,
            room_chat_msg_id=67890,
            discussion_msg_id=11111,
            json_text={"title": "Test Question", "body": "Question body"},
        )

    def tearDown(self):
        Question.objects.filter(id=self.question.id).delete()
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890")
    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_DISCUSSION_ID", "-100987654321")
    @patch("helpdeskbot.handlers.answers.send_message")
    @patch("helpdeskbot.handlers.answers.notify_user_about_answer", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.answers.Answer.create_from_update")
    async def test_creates_answer_forwards_to_channel_and_notifies(
        self, mock_create_answer, mock_notify, mock_send
    ):
        """Should create answer, forward to channel, send confirmation, and notify user"""
        # Create update where user replies to a question in a room chat
        update = create_reply_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-100123456789,
            text="This is the answer",
            reply_to_text="Question posted in room",
            reply_to_message_id=67890
        )

        # Create a mock question with room
        mock_question = MagicMock()
        mock_question.user = self.user
        mock_question.discussion_msg_id = 11111
        mock_question.channel_msg_id = 12345
        mock_question.room = self.room

        # Patch the rooms dict and Question query
        mock_room_ref = MagicMock(slug="test-room", title="Test Room", chat_id="-100123456789")

        with patch.dict("helpdeskbot.handlers.answers.rooms", {"-100123456789": mock_room_ref}, clear=False):
            with patch("helpdeskbot.handlers.answers.Question.objects") as mock_q:
                # afirst() is async, so we need AsyncMock
                mock_q.filter.return_value.select_related.return_value.afirst = AsyncMock(return_value=mock_question)

                await handle_answer_from_room_chat(update)

        # Verify answer was created
        mock_create_answer.assert_called_once()

        # Verify user was notified
        mock_notify.assert_called_once()

        # Verify messages were sent (forward to channel + confirmation to room)
        self.assertEqual(mock_send.call_count, 2)

    @patch("helpdeskbot.handlers.answers.log")
    async def test_handles_missing_message_id(self, mock_log):
        """Should log error when reply_to_message.message_id is 0 (falsy)"""
        # Create a reply update with message_id=0 (falsy value)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-100123456789,
            text="Answer",
            reply_to_text="Question",
            reply_to_message_id=0  # Falsy value
        )

        result = await handle_answer_from_room_chat(update)

        self.assertIsNone(result)
        mock_log.error.assert_called_once()


class NotifyUserAboutAnswerTest(AnswersTestBase):
    """Test notify_user_about_answer function"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="questioner@example.com", telegram_id="111")

        self.question = Question.objects.create(
            user=self.user,
            channel_msg_id=12345,
            json_text={"title": "Test Question", "body": "Question body"},
        )

    def tearDown(self):
        Question.objects.filter(id=self.question.id).delete()
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.answers.send_message")
    @patch("helpdeskbot.handlers.answers.render_html_message")
    async def test_sends_notification_to_question_author(self, mock_render, mock_send):
        """Should send notification to question author"""
        mock_render.return_value = "Notification text"

        update = create_message_update(
            bot=self.bot,
            telegram_id=222,  # Different from question author
            chat_id=-100123456,
            text="Answer text",
            message_id=99999
        )

        await notify_user_about_answer(update, self.question)

        # Verify message was sent to user
        mock_send.assert_called_once_with(
            chat_id=int(self.user.telegram_id),
            text="Notification text",
        )

    @patch("helpdeskbot.handlers.answers.log")
    async def test_handles_question_without_user(self, mock_log):
        """Should log info when question has no user"""
        question_no_user = await Question.objects.acreate(
            user=None,
            channel_msg_id=99999,
            json_text={"title": "Test", "body": "Body"},
        )

        update = create_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-100123456,
            text="Answer"
        )

        result = await notify_user_about_answer(update, question_no_user)

        self.assertIsNone(result)
        mock_log.info.assert_called_once()

        await question_no_user.adelete()

    @patch("helpdeskbot.handlers.answers.log")
    async def test_skips_notification_for_self_reply(self, mock_log):
        """Should skip notification when user replies to their own question"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=int(self.user.telegram_id),  # Same as question author
            chat_id=-100123456,
            text="Self reply"
        )

        result = await notify_user_about_answer(update, self.question)

        self.assertIsNone(result)
        mock_log.debug.assert_called_once()


class OnReplyMessageTest(AnswersTestBase):
    """Test on_reply_message routing function"""

    @patch("helpdeskbot.handlers.answers.handle_answer_from_channel")
    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890")
    async def test_routes_to_channel_handler(self, mock_handle_channel):
        """Should route to channel handler when reply is forwarded from channel"""
        # Create update replying to a forwarded message from channel
        update = create_forwarded_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-1001234567890,
            text="Answer text",
            forward_from_chat_id=-1001234567890,
            forward_from_message_id=12345
        )

        await on_reply_message(update, None)

        mock_handle_channel.assert_called_once_with(update)

    @patch("helpdeskbot.handlers.answers.handle_answer_from_room_chat")
    async def test_routes_to_room_handler(self, mock_handle_room):
        """Should route to room handler when reply is in a room chat"""
        # Create update replying to a message in a room (not forwarded)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=-100123456,
            text="Answer text",
            reply_to_text="Question in room"
        )
        # create_reply_update creates non-forwarded messages by default (no forward_origin)

        with patch.dict("helpdeskbot.handlers.answers.rooms", {"-100123456": MagicMock()}, clear=False):
            await on_reply_message(update, None)

        mock_handle_room.assert_called_once_with(update)

    async def test_returns_none_for_invalid_update(self):
        """Should return None for updates without proper structure"""
        from telegram import Update, Message
        import time

        # No message - create Update with message=None
        update_no_msg = Update(update_id=1, message=None)
        self.assertIsNone(await on_reply_message(update_no_msg, None))

        # No reply_to_message - create Message without reply_to_message using de_json
        msg_dict = {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 222, "is_bot": False, "first_name": "Test"},
            "text": "text"
        }
        message = Message.de_json(msg_dict, self.bot)
        update_no_reply = Update(update_id=2, message=message)
        self.assertIsNone(await on_reply_message(update_no_reply, None))

        # No text - create reply message with text=None
        reply_msg_dict = {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 222, "is_bot": False, "first_name": "Test"},
            "reply_to_message": {
                "message_id": 0,
                "date": int(time.time()) - 100,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 111, "is_bot": False, "first_name": "Original"},
                "text": "original"
            }
        }
        message_no_text = Message.de_json(reply_msg_dict, self.bot)
        update_no_text = Update(update_id=3, message=message_no_text)
        self.assertIsNone(await on_reply_message(update_no_text, None))
