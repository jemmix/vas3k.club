"""Tests for helpdeskbot/handlers/question.py ConversationHandler"""

import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from django.test import TestCase
from telegram import Update
from telegram.ext import ConversationHandler, CallbackContext

from bot.test_helpers import (
    create_test_user,
    create_command_update,
    create_message_update,
    create_forwarded_message_update,
)
from helpdeskbot.models import Question, HelpDeskUser
from notifications.telegram.tests import BaseTelegramTest

# Import handlers after patching token
with patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"):
    from helpdeskbot.handlers.question import (
        start,
        request_title_value,
        request_body_value,
        request_room_choose,
        input_response,
        cancel_question,
        review_question,
        edit_question,
        finish_review,
        publish_question,
        fallback,
        error_fallback,
        update_discussion_message_id,
        State,
        QuestionKeyboard,
        ReviewKeyboard,
        CUR_FIELD_KEY,
    )


@patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
class QuestionTestBase(BaseTelegramTest, TestCase):
    """Base class with token patch and bot setup for all question handler tests"""
    tags = {"telegram", "telegram_helpdesk"}


class StartTest(QuestionTestBase):
    """Test start handler"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="test@example.com", telegram_id="123")

    def tearDown(self):
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.render_html_message")
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_starts_conversation_for_valid_user(self, mock_get_user, mock_render, mock_send):
        """Should start conversation and return REQUEST_FOR_INPUT"""
        mock_get_user.return_value = self.user
        mock_render.return_value = "Welcome message"

        update = create_command_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            command="start"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await start(update, context)

        self.assertEqual(result, State.REQUEST_FOR_INPUT)
        mock_send.assert_called_once()
        # Verify user_data was cleared (should be empty dict)
        self.assertEqual(context.user_data, {})

    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_returns_end_if_no_user(self, mock_get_user):
        """Should return END if user not found"""
        mock_get_user.return_value = None

        update = create_command_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            command="start"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await start(update, context)

        self.assertEqual(result, ConversationHandler.END)

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_returns_end_if_user_banned(self, mock_get_user, mock_send):
        """Should return END if user is banned in HelpDeskUser"""
        mock_get_user.return_value = self.user

        # Create banned HelpDeskUser (banned_until in future means banned)
        HelpDeskUser.objects.create(
            user=self.user,
            banned_until=datetime.utcnow() + timedelta(days=7)
        )

        update = create_command_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            command="start"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await start(update, context)

        self.assertEqual(result, ConversationHandler.END)
        mock_send.assert_called_once()
        self.assertIn("забанили", mock_send.call_args[0][1])

        HelpDeskUser.objects.filter(user=self.user).delete()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.config.DAILY_QUESTION_LIMIT", 3)
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_returns_end_if_daily_limit_exceeded(self, mock_get_user, mock_send):
        """Should return END if non-moderator exceeds daily question limit"""
        mock_get_user.return_value = self.user

        # Create 3 questions in last 24h
        now = datetime.utcnow()
        for i in range(3):
            Question.objects.create(
                user=self.user,
                channel_msg_id=str(1000 + i),
                json_text={"title": f"Q{i}", "body": "body"},
                created_at=now - timedelta(hours=12),
            )

        update = create_command_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            command="start"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await start(update, context)

        self.assertEqual(result, ConversationHandler.END)
        mock_send.assert_called_once()
        self.assertIn("лимит", mock_send.call_args[0][1])

        # Cleanup
        Question.objects.filter(user=self.user).delete()


class RequestFieldValueTest(QuestionTestBase):
    """Test field request handlers"""

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_request_title_value(self, mock_send):
        """Should set CUR_FIELD_KEY to TITLE and prompt for input"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await request_title_value(update, context)

        self.assertEqual(result, State.INPUT_RESPONSE)
        self.assertEqual(context.user_data[CUR_FIELD_KEY], QuestionKeyboard.TITLE.value)
        mock_send.assert_called_once()
        self.assertIn("Введите заголовок", mock_send.call_args[0][1])

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_request_body_value(self, mock_send):
        """Should set CUR_FIELD_KEY to BODY and prompt for input"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await request_body_value(update, context)

        self.assertEqual(result, State.INPUT_RESPONSE)
        self.assertEqual(context.user_data[CUR_FIELD_KEY], QuestionKeyboard.BODY.value)
        mock_send.assert_called_once()
        self.assertIn("Введите текст вопроса", mock_send.call_args[0][1])

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_request_room_choose(self, mock_send):
        """Should set CUR_FIELD_KEY to ROOM and show room keyboard"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await request_room_choose(update, context)

        self.assertEqual(result, State.INPUT_RESPONSE)
        self.assertEqual(context.user_data[CUR_FIELD_KEY], QuestionKeyboard.ROOM.value)
        mock_send.assert_called_once()
        self.assertIn("Выберите один из чатов", mock_send.call_args[0][1])


class InputResponseTest(QuestionTestBase):
    """Test input_response handler"""

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_stores_user_input_and_returns_to_menu(self, mock_send):
        """Should store user input for current field and return to menu"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="My question title"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {CUR_FIELD_KEY: QuestionKeyboard.TITLE.value}

        result = await input_response(update, context)

        self.assertEqual(result, State.REQUEST_FOR_INPUT)
        self.assertEqual(context.user_data[QuestionKeyboard.TITLE.value], "My question title")
        self.assertNotIn(CUR_FIELD_KEY, context.user_data)
        mock_send.assert_called_once()


class CancelQuestionTest(QuestionTestBase):
    """Test cancel_question handler"""

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_cancels_conversation(self, mock_send):
        """Should send cancellation message and end conversation"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await cancel_question(update, context)

        self.assertEqual(result, ConversationHandler.END)
        mock_send.assert_called_once()
        self.assertIn("отменено", mock_send.call_args[0][1])


class ReviewQuestionTest(QuestionTestBase):
    """Test review_question handler"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="test@example.com", telegram_id="123")

    def tearDown(self):
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.render_html_message")
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_shows_review_when_valid(self, mock_get_user, mock_render, mock_send):
        """Should show review when title and body are valid"""
        mock_get_user.return_value = self.user
        mock_render.return_value = "Question preview"

        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.TITLE.value: "Test title",
            QuestionKeyboard.BODY.value: "Test body",
        }

        result = await review_question(update, context)

        self.assertEqual(result, State.FINISH_REVIEW)
        mock_send.assert_called_once()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.edit_question", new_callable=AsyncMock)
    async def test_rejects_empty_title(self, mock_edit, mock_send):
        """Should reject if title is empty"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.BODY.value: "Test body",
        }

        result = await review_question(update, context)

        mock_send.assert_called_once()
        self.assertIn("обязательны", mock_send.call_args[0][1])
        mock_edit.assert_called_once()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.edit_question", new_callable=AsyncMock)
    async def test_rejects_empty_body(self, mock_edit, mock_send):
        """Should reject if body is empty"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.TITLE.value: "Test title",
        }

        result = await review_question(update, context)

        mock_send.assert_called_once()
        self.assertIn("обязательны", mock_send.call_args[0][1])
        mock_edit.assert_called_once()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.edit_question", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.config.QUESTION_TITLE_MAX_LEN", 10)
    @patch("helpdeskbot.handlers.question.config.QUESTION_BODY_MAX_LEN", 5000)
    async def test_rejects_title_too_long(self, mock_edit, mock_send):
        """Should reject if title exceeds max length"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.TITLE.value: "A" * 20,  # Too long
            QuestionKeyboard.BODY.value: "Test body",
        }

        result = await review_question(update, context)

        mock_send.assert_called_once()
        self.assertIn("не должен быть длиннее", mock_send.call_args[0][1])
        mock_edit.assert_called_once()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.edit_question", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.config.QUESTION_BODY_MAX_LEN", 50)
    @patch("helpdeskbot.handlers.question.config.QUESTION_TITLE_MAX_LEN", 200)
    async def test_rejects_body_too_long(self, mock_edit, mock_send):
        """Should reject if body exceeds max length"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.TITLE.value: "Test title",
            QuestionKeyboard.BODY.value: "A" * 100,  # Too long
        }

        result = await review_question(update, context)

        mock_send.assert_called_once()
        self.assertIn("не может быть длиннее", mock_send.call_args[0][1])
        mock_edit.assert_called_once()


class EditQuestionTest(QuestionTestBase):
    """Test edit_question handler"""

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_returns_to_menu(self, mock_send):
        """Should return to REQUEST_FOR_INPUT state"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await edit_question(update, context)

        self.assertEqual(result, State.REQUEST_FOR_INPUT)
        mock_send.assert_called_once()


class PublishQuestionTest(QuestionTestBase):
    """Test publish_question function"""

    def setUp(self):
        from rooms.models import Room

        super().setUp()
        self.user = create_test_user(email="test@example.com", telegram_id="123")

        # Create a real Room for testing
        self.room = Room.objects.create(
            slug="test-room",
            title="Test Room",
            color="#000000",
            chat_id="-100123456",
        )

    def tearDown(self):
        Question.objects.filter(user=self.user).delete()
        self.user.delete()
        self.room.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.question.send_message", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.render_html_message")
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_publishes_question_without_room(self, mock_get_user, mock_render, mock_send):
        """Should create question and send to channel only"""
        mock_get_user.return_value = self.user
        mock_render.return_value = "Question text"

        mock_channel_msg = MagicMock()
        mock_channel_msg.message_id = 12345
        mock_send.return_value = mock_channel_msg

        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        user_data = {
            QuestionKeyboard.TITLE.value: "Test title",
            QuestionKeyboard.BODY.value: "Test body",
        }

        link = await publish_question(update, user_data)

        # Verify question created
        question = await Question.objects.filter(user=self.user).afirst()
        self.assertIsNotNone(question)
        self.assertEqual(question.channel_msg_id, "12345")

        # Verify channel message sent
        self.assertEqual(mock_send.call_count, 1)

        # Verify link returned
        self.assertIn("12345", link)

    @patch("helpdeskbot.handlers.question.send_message", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.render_html_message")
    @patch("helpdeskbot.handlers.question.get_club_user", new_callable=AsyncMock)
    async def test_publishes_question_with_room(self, mock_get_user, mock_render, mock_send):
        """Should create question and send to both channel and room"""
        mock_get_user.return_value = self.user
        mock_render.return_value = "Question text"

        mock_channel_msg = MagicMock()
        mock_channel_msg.message_id = 12345

        mock_room_msg = MagicMock()
        mock_room_msg.message_id = 67890

        mock_send.side_effect = [mock_channel_msg, mock_room_msg]

        # Patch the rooms dict to include our real room
        with patch.dict("helpdeskbot.handlers.question.rooms", {"Test Room": self.room}, clear=False):
            update = create_message_update(
                bot=self.bot,
                telegram_id=123,
                chat_id=12345,
                text="dummy"
            )
            user_data = {
                QuestionKeyboard.TITLE.value: "Test title",
                QuestionKeyboard.BODY.value: "Test body",
                QuestionKeyboard.ROOM.value: "Test Room",
            }

            link = await publish_question(update, user_data)

        # Verify question created with room info
        question = await Question.objects.filter(user=self.user).afirst()
        self.assertIsNotNone(question)
        self.assertEqual(question.channel_msg_id, "12345")
        self.assertEqual(question.room_chat_msg_id, "67890")
        self.assertEqual(question.room, self.room)

        # Verify both messages sent
        self.assertEqual(mock_send.call_count, 2)


class FinishReviewTest(QuestionTestBase):
    """Test finish_review handler"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="test@example.com", telegram_id="123")

    def tearDown(self):
        Question.objects.filter(user=self.user).delete()
        self.user.delete()
        super().tearDown()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    @patch("helpdeskbot.handlers.question.publish_question", new_callable=AsyncMock)
    async def test_publishes_on_create_button(self, mock_publish, mock_send):
        """Should publish question when CREATE button clicked"""
        mock_publish.return_value = "https://t.me/c/123/456"

        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text=ReviewKeyboard.CREATE.value
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {
            QuestionKeyboard.TITLE.value: "Test",
            QuestionKeyboard.BODY.value: "Body",
        }

        result = await finish_review(update, context)

        self.assertEqual(result, ConversationHandler.END)
        mock_publish.assert_called_once()
        mock_send.assert_called_once()
        self.assertIn("опубликован", mock_send.call_args[0][1])

    @patch("helpdeskbot.handlers.question.edit_question", new_callable=AsyncMock)
    async def test_edits_on_edit_button(self, mock_edit):
        """Should return to edit when EDIT button clicked"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text=ReviewKeyboard.EDIT.value
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await finish_review(update, context)

        mock_edit.assert_called_once()

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_handles_unexpected_command(self, mock_send):
        """Should handle unexpected text in review state"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="unexpected text"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await finish_review(update, context)

        mock_send.assert_called_once()
        self.assertIn("Неожиданная команда", mock_send.call_args[0][1])


class FallbackHandlersTest(QuestionTestBase):
    """Test fallback handlers"""

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_fallback_prompts_menu_selection(self, mock_send):
        """Should prompt user to select menu option"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await fallback(update, context)

        self.assertEqual(result, State.REQUEST_FOR_INPUT)
        mock_send.assert_called_once()
        self.assertIn("не выбрали действие", mock_send.call_args[0][1])

    @patch("helpdeskbot.handlers.question.send_reply", new_callable=AsyncMock)
    async def test_error_fallback_ends_conversation(self, mock_send):
        """Should end conversation on error"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=123,
            chat_id=12345,
            text="dummy"
        )
        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot
        context.user_data = {}

        result = await error_fallback(update, context)

        self.assertEqual(result, ConversationHandler.END)
        mock_send.assert_called_once()
        self.assertIn("пошло не так", mock_send.call_args[0][1])


class UpdateDiscussionMessageIdTest(QuestionTestBase):
    """Test update_discussion_message_id function"""

    def setUp(self):
        super().setUp()
        self.user = create_test_user(email="test@example.com", telegram_id="123")
        self.question = Question.objects.create(
            user=self.user,
            channel_msg_id=12345,
            json_text={"title": "Test", "body": "Body"},
        )

    def tearDown(self):
        Question.objects.filter(id=self.question.id).delete()
        self.user.delete()
        super().tearDown()

    async def test_updates_discussion_message_id(self):
        """Should update question with discussion_msg_id from forward"""
        # Create a message that represents a forward from a channel
        from telegram import Chat as TgChat, User as TgUser, Message

        tg_user = TgUser(id=123, is_bot=False, first_name="Test")
        tg_chat = TgChat(id=12345, type="group")
        tg_chat.set_bot(self.bot)

        forward_from_chat = TgChat(id=-1001234567890, type="channel")
        forward_from_chat.set_bot(self.bot)

        message = Message(
            message_id=67890,
            date=int(time.time()),
            chat=tg_chat,
            from_user=tg_user,
            text="Forwarded discussion",
            forward_from_chat=forward_from_chat,
            forward_from_message_id=12345,  # This is the channel message ID
        )
        message.set_bot(self.bot)

        update = Update(update_id=1, message=message)

        await update_discussion_message_id(update)

        # Refresh from DB
        self.question.refresh_from_db()
        self.assertEqual(self.question.discussion_msg_id, "67890")
