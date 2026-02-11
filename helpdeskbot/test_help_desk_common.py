"""Tests for helpdeskbot/help_desk_common.py wrapper functions."""

from unittest.mock import patch, MagicMock

from django.test import TestCase
from telegram.constants import ParseMode


@patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
class HelpDeskCommonTestBase(TestCase):
    """Base class with token patch for all helpdesk common tests"""
    tags = {"telegram", "telegram_helpdesk"}


# Import after patching to ensure bot initializes with test token
with patch("helpdeskbot.config.TELEGRAM_HELP_DESK_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"):
    from helpdeskbot.help_desk_common import (
        send_message,
        edit_message,
        send_reply,
        get_channel_message_link,
        get_chat_message_link,
    )


class SendMessageTest(HelpDeskCommonTestBase):
    """Test send_message wrapper function"""

    @patch("helpdeskbot.help_desk_common.bot")
    async def test_sends_message_with_default_params(self, mock_bot):
        """Should call bot.send_message with defaults"""
        send_message(chat_id=12345, text="Test message")

        mock_bot.send_message.assert_called_once_with(
            chat_id=12345,
            text="Test message",
            reply_to_message_id=None,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    @patch("helpdeskbot.help_desk_common.bot")
    async def test_sends_message_with_custom_params(self, mock_bot):
        """Should call bot.send_message with custom parameters"""
        send_message(
            chat_id=12345,
            text="Test message",
            reply_to_message_id=999,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )

        mock_bot.send_message.assert_called_once_with(
            chat_id=12345,
            text="Test message",
            reply_to_message_id=999,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )


class EditMessageTest(HelpDeskCommonTestBase):
    """Test edit_message wrapper function"""

    @patch("helpdeskbot.help_desk_common.bot")
    async def test_edits_message_with_defaults(self, mock_bot):
        """Should call bot.edit_message_text with defaults"""
        edit_message(chat_id=12345, message_id=999, new_text="Updated text")

        mock_bot.edit_message_text.assert_called_once_with(
            text="Updated text",
            chat_id=12345,
            message_id=999,
            parse_mode=ParseMode.HTML,
        )

    @patch("helpdeskbot.help_desk_common.bot")
    async def test_edits_message_with_custom_parse_mode(self, mock_bot):
        """Should call bot.edit_message_text with custom parse mode"""
        edit_message(
            chat_id=12345,
            message_id=999,
            new_text="Updated text",
            parse_mode=ParseMode.MARKDOWN,
        )

        mock_bot.edit_message_text.assert_called_once_with(
            text="Updated text",
            chat_id=12345,
            message_id=999,
            parse_mode=ParseMode.MARKDOWN,
        )


class SendReplyTest(HelpDeskCommonTestBase):
    """Test send_reply wrapper function"""

    async def test_sends_reply_with_defaults(self):
        """Should call update.message.reply_text with defaults"""
        mock_update = MagicMock()
        mock_update.message.reply_text = MagicMock()

        send_reply(mock_update, "Reply text")

        mock_update.message.reply_text.assert_called_once_with(
            text="Reply text",
            parse_mode=ParseMode.HTML,
            reply_markup=None,
            disable_web_page_preview=True,
        )

    async def test_sends_reply_with_custom_params(self):
        """Should call update.message.reply_text with custom parameters"""
        mock_update = MagicMock()
        mock_update.message.reply_text = MagicMock()
        mock_reply_markup = MagicMock()

        send_reply(
            mock_update,
            "Reply text",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mock_reply_markup,
            disable_web_page_preview=False,
        )

        mock_update.message.reply_text.assert_called_once_with(
            text="Reply text",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mock_reply_markup,
            disable_web_page_preview=False,
        )


class GetChannelMessageLinkTest(HelpDeskCommonTestBase):
    """Test get_channel_message_link pure function"""

    @patch("helpdeskbot.help_desk_common.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-1001234567890")
    async def test_constructs_channel_link(self):
        """Should construct correct channel message link"""
        link = get_channel_message_link("12345")

        # Channel ID -1001234567890 should become 1234567890 (removes -100 prefix)
        self.assertEqual(link, "https://t.me/c/1234567890/12345")

    @patch("helpdeskbot.help_desk_common.config.TELEGRAM_HELP_DESK_BOT_QUESTION_CHANNEL_ID", "-100999888777")
    async def test_constructs_channel_link_different_id(self):
        """Should handle different channel IDs correctly"""
        link = get_channel_message_link("67890")

        self.assertEqual(link, "https://t.me/c/999888777/67890")


class GetChatMessageLinkTest(HelpDeskCommonTestBase):
    """Test get_chat_message_link pure function"""

    async def test_constructs_chat_link(self):
        """Should construct correct chat message link"""
        link = get_chat_message_link("1234567890", "12345")

        self.assertEqual(link, "https://t.me/c/1234567890/12345")

    async def test_constructs_chat_link_with_different_ids(self):
        """Should handle various chat and message IDs"""
        link = get_chat_message_link("999888777", "67890")

        self.assertEqual(link, "https://t.me/c/999888777/67890")
