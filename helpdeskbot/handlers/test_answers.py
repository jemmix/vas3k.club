"""Tests for helpdeskbot/handlers/answers.py"""

from unittest.mock import patch, MagicMock

from django.test import TestCase

from bot.test_helpers import create_test_user
from helpdeskbot.models import Question, Answer
from helpdeskbot.room import Room

# Import handlers after patching token
with patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"):
    from helpdeskbot.handlers.answers import (
        on_reply_message,
        handle_answer_from_channel,
        handle_answer_from_room_chat,
        notify_user_about_answer,
    )


@patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
class AnswersTestBase(TestCase):
    """Base class with token patch for all answer handler tests"""
    tags = {"telegram", "telegram_helpdesk"}


class HandleAnswerFromChannelTest(AnswersTestBase):
    """Test handle_answer_from_channel function"""

    def setUp(self):
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

    @patch("helpdeskbot.handlers.answers.notify_user_about_answer")
    @patch("helpdeskbot.handlers.answers.Answer.create_from_update")
    def test_creates_answer_and_notifies_user(self, mock_create_answer, mock_notify):
        """Should create answer from update and notify user"""
        # Create mock update
        mock_update = MagicMock()
        mock_update.message.reply_to_message.forward_from_message_id = 12345

        handle_answer_from_channel(mock_update)

        # Verify answer was created
        mock_create_answer.assert_called_once()
        question_arg = mock_create_answer.call_args[0][0]
        self.assertEqual(question_arg.id, self.question.id)

        # Verify user was notified
        mock_notify.assert_called_once()

    @patch("helpdeskbot.handlers.answers.log")
    def test_handles_missing_forward_message_id(self, mock_log):
        """Should log error when forward_from_message_id is None"""
        mock_update = MagicMock()
        mock_update.message.reply_to_message.forward_from_message_id = None

        result = handle_answer_from_channel(mock_update)

        self.assertIsNone(result)
        mock_log.error.assert_called_once()

    @patch("helpdeskbot.handlers.answers.log")
    def test_handles_question_not_found(self, mock_log):
        """Should log warning when question is not found"""
        mock_update = MagicMock()
        mock_update.message.reply_to_message.forward_from_message_id = 99999  # Non-existent

        result = handle_answer_from_channel(mock_update)

        self.assertIsNone(result)
        mock_log.warning.assert_called_once()


class HandleAnswerFromRoomChatTest(AnswersTestBase):
    """Test handle_answer_from_room_chat function"""

    def setUp(self):
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

    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890")
    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_DISCUSSION_ID", "-100987654321")
    @patch("helpdeskbot.handlers.answers.send_message")
    @patch("helpdeskbot.handlers.answers.notify_user_about_answer")
    @patch("helpdeskbot.handlers.answers.Answer.create_from_update")
    def test_creates_answer_forwards_to_channel_and_notifies(
        self, mock_create_answer, mock_notify, mock_send
    ):
        """Should create answer, forward to channel, send confirmation, and notify user"""
        # Create mock update
        mock_update = MagicMock()
        mock_update.message.reply_to_message.message_id = 67890
        mock_update.message.chat.id = -100123456789
        mock_update.message.message_id = 99999
        mock_update.message.text = "This is the answer"
        mock_update.message.from_user.id = 222
        mock_update.message.from_user.first_name = "Answerer"

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
                mock_q.filter.return_value.select_related.return_value.first.return_value = mock_question

                handle_answer_from_room_chat(mock_update)

        # Verify answer was created
        mock_create_answer.assert_called_once()

        # Verify user was notified
        mock_notify.assert_called_once()

        # Verify messages were sent (forward to channel + confirmation to room)
        self.assertEqual(mock_send.call_count, 2)

    @patch("helpdeskbot.handlers.answers.log")
    def test_handles_missing_message_id(self, mock_log):
        """Should log error when reply_to_message.message_id is None"""
        mock_update = MagicMock()
        mock_update.message.reply_to_message.message_id = None

        result = handle_answer_from_room_chat(mock_update)

        self.assertIsNone(result)
        mock_log.error.assert_called_once()


class NotifyUserAboutAnswerTest(AnswersTestBase):
    """Test notify_user_about_answer function"""

    def setUp(self):
        self.user = create_test_user(email="questioner@example.com", telegram_id="111")

        self.question = Question.objects.create(
            user=self.user,
            channel_msg_id=12345,
            json_text={"title": "Test Question", "body": "Question body"},
        )

    def tearDown(self):
        Question.objects.filter(id=self.question.id).delete()
        self.user.delete()

    @patch("helpdeskbot.handlers.answers.send_message")
    @patch("helpdeskbot.handlers.answers.render_html_message")
    def test_sends_notification_to_question_author(self, mock_render, mock_send):
        """Should send notification to question author"""
        mock_render.return_value = "Notification text"

        mock_update = MagicMock()
        mock_update.message.from_user.id = 222  # Different from question author
        mock_update.message.chat.id = -100123456
        mock_update.message.message_id = 99999
        mock_update.message.text = "Answer text"

        notify_user_about_answer(mock_update, self.question)

        # Verify message was sent to user
        mock_send.assert_called_once_with(
            chat_id=int(self.user.telegram_id),
            text="Notification text",
        )

    @patch("helpdeskbot.handlers.answers.log")
    def test_handles_question_without_user(self, mock_log):
        """Should log info when question has no user"""
        question_no_user = Question.objects.create(
            user=None,
            channel_msg_id=99999,
            json_text={"title": "Test", "body": "Body"},
        )

        mock_update = MagicMock()

        result = notify_user_about_answer(mock_update, question_no_user)

        self.assertIsNone(result)
        mock_log.info.assert_called_once()

        question_no_user.delete()

    @patch("helpdeskbot.handlers.answers.log")
    def test_skips_notification_for_self_reply(self, mock_log):
        """Should skip notification when user replies to their own question"""
        mock_update = MagicMock()
        mock_update.message.from_user.id = int(self.user.telegram_id)  # Same as question author

        result = notify_user_about_answer(mock_update, self.question)

        self.assertIsNone(result)
        mock_log.debug.assert_called_once()


class OnReplyMessageTest(AnswersTestBase):
    """Test on_reply_message routing function"""

    @patch("helpdeskbot.handlers.answers.handle_answer_from_channel")
    @patch("helpdeskbot.handlers.answers.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890")
    def test_routes_to_channel_handler(self, mock_handle_channel):
        """Should route to channel handler when reply is forwarded from channel"""
        mock_update = MagicMock()
        mock_update.message.reply_to_message.forward_from_chat.id = -1001234567890
        mock_update.message.text = "Answer text"

        on_reply_message(mock_update, None)

        mock_handle_channel.assert_called_once_with(mock_update)

    @patch("helpdeskbot.handlers.answers.handle_answer_from_room_chat")
    def test_routes_to_room_handler(self, mock_handle_room):
        """Should route to room handler when reply is in a room chat"""
        mock_update = MagicMock()
        mock_update.message.reply_to_message.forward_from_chat = None
        mock_update.message.reply_to_message.chat.id = "-100123456"
        mock_update.message.text = "Answer text"

        with patch.dict("helpdeskbot.handlers.answers.rooms", {"-100123456": MagicMock()}, clear=False):
            on_reply_message(mock_update, None)

        mock_handle_room.assert_called_once_with(mock_update)

    def test_returns_none_for_invalid_update(self):
        """Should return None for updates without proper structure"""
        # No message
        mock_update = MagicMock()
        mock_update.message = None
        self.assertIsNone(on_reply_message(mock_update, None))

        # No reply_to_message
        mock_update = MagicMock()
        mock_update.message.reply_to_message = None
        self.assertIsNone(on_reply_message(mock_update, None))

        # No text
        mock_update = MagicMock()
        mock_update.message.text = None
        self.assertIsNone(on_reply_message(mock_update, None))
