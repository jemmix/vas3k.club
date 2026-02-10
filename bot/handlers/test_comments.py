"""Tests for bot/handlers/comments.py handlers."""

from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from telegram.ext import CallbackContext

from bot.handlers.comments import comment, reply_to_comment, comment_to_post
from bot.test_helpers import (
    create_test_user,
    create_message_update,
    create_reply_update,
)
from comments.models import Comment
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post
from telegram import MessageEntity


class CommentRouterTest(BaseTelegramTest, TestCase):
    """Test the comment() router function"""

    tags = {"telegram", "telegram_bot"}

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")

        # Mock close_old_connections to prevent DB connection issues
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

    def tearDown(self):
        super().tearDown()
        self.user.delete()
        self.close_old_connections_patch.stop()

    def test_skips_non_reply(self):
        """Should skip messages that are not replies"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Not a reply"
        )
        # Explicitly set reply_to_message to None
        update.message.reply_to_message = None

        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot  # Use real bot (getMe is handled by mock server)

        result = comment(update, context)

        self.assertIsNone(result)

    def test_skips_reply_to_other_user(self):
        """Should skip replies to other users (not bot)"""
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Reply to other user",
            reply_to_text="Original message",
            reply_to_user_id=999  # Not the bot (bot.id will be 123456 from getMe)
        )

        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot  # Use real bot (getMe is handled by mock server)

        result = comment(update, context)

        self.assertIsNone(result)

    @patch('bot.handlers.comments.reply_to_comment')
    def test_routes_to_reply_to_comment(self, mock_reply_to_comment):
        """Should route to reply_to_comment when message starts with comment emoji"""
        # Create update replying to a bot message with comment emoji
        # Bot ID is 123456 (from getMe route in BaseTelegramTest)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="My reply to the comment",
            reply_to_text="💬 Original comment text",
            reply_to_user_id=123456  # Replying to bot
        )

        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot  # Use real bot (getMe is handled by mock server)

        comment(update, context)

        mock_reply_to_comment.assert_called_once_with(update, context)

    @patch('bot.handlers.comments.comment_to_post')
    def test_routes_to_comment_to_post(self, mock_comment_to_post):
        """Should route to comment_to_post when message starts with post emoji"""
        # Create update replying to a bot message with post emoji
        # Bot ID is 123456 (from getMe route in BaseTelegramTest)
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="My comment on the post",
            reply_to_text="📝 Post title and text...",
            reply_to_user_id=123456  # Replying to bot
        )

        context = MagicMock(spec=CallbackContext)
        context.bot = self.bot  # Use real bot (getMe is handled by mock server)

        comment(update, context)

        mock_comment_to_post.assert_called_once_with(update, context)


class ReplyToCommentTest(BaseTelegramTest, TestCase):
    """Test the reply_to_comment handler"""

    tags = {"telegram", "telegram_bot"}

    REPLY_TEXT_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            slug="test-post",
            title="Test Post",
            text="Test content",
            visibility=Post.VISIBILITY_EVERYWHERE,
        )
        self.comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Original comment",
        )

        # Mock functions
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.rate_limit_patch = patch("bot.handlers.comments.is_comment_rate_limit_exceeded", return_value=False)
        self.async_task_patch = patch("bot.handlers.comments.async_task")
        self.update_counters_patch = patch("bot.handlers.comments.Comment.update_post_counters")
        self.increment_unread_patch = patch("bot.handlers.comments.PostView.increment_unread_comments")
        self.register_view_patch = patch("bot.handlers.comments.PostView.register_view")
        self.update_index_patch = patch("bot.handlers.comments.SearchIndex.update_comment_index")
        self.create_links_patch = patch("bot.handlers.comments.LinkedPost.create_links_from_text")
        self.cached_users_patch = patch("bot.decorators.cached_telegram_users", return_value={str(self.user.telegram_id): self.user.id})

        self.close_old_connections_patch.start()
        self.rate_limit_patch.start()
        self.async_task_patch.start()
        self.update_counters_patch.start()
        self.increment_unread_patch.start()
        self.register_view_patch.start()
        self.update_index_patch.start()
        self.create_links_patch.start()
        self.cached_users_patch.start()

    def tearDown(self):
        super().tearDown()
        Comment.objects.filter(post=self.post).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()
        self.close_old_connections_patch.stop()
        self.rate_limit_patch.stop()
        self.async_task_patch.stop()
        self.update_counters_patch.stop()
        self.increment_unread_patch.stop()
        self.register_view_patch.stop()
        self.update_index_patch.stop()
        self.create_links_patch.stop()
        self.cached_users_patch.stop()

    @override_settings(APP_HOST="https://vas3k.club")
    def test_creates_reply_comment(self):
        """Should create a reply to existing comment"""
        comment_url = f"https://vas3k.club/post/{self.post.slug}/#comment-{self.comment.id}"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=comment_url,
        )

        # Register route for sendMessage - we'll check the exact body after
        self.server.add_route(
            self.REPLY_TEXT_PATH,
            '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}'
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="This is my reply",
            reply_to_text="💬 Original comment",
            reply_to_entities=[entity],
        )
        context = MagicMock()

        reply_to_comment(update, context)

        # Verify comment was created
        new_comment = Comment.objects.filter(post=self.post, reply_to=self.comment).first()
        self.assertIsNotNone(new_comment)
        self.assertEqual(new_comment.author, self.user)
        self.assertIn("This is my reply", new_comment.text)
        self.assertIn(f"@{self.comment.author.slug}", new_comment.text)

        # Now we know the comment ID, verify the exact message sent
        # The handler uses settings.APP_HOST which is http://127.0.0.1:8000 in tests
        expected_url = f"http://127.0.0.1:8000/post/{self.post.slug}/comment/{new_comment.id}/"
        expected_text = f'➜ <a href="{expected_url}">Отвечено</a> 👍'

        send_message_requests = [r for r in self.server.requests_received if r.path == self.REPLY_TEXT_PATH]
        self.assertEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertEqual(sent_request.body["text"], expected_text)
        self.assertEqual(sent_request.body["parse_mode"], "HTML")
        self.assertEqual(sent_request.body["disable_web_page_preview"], "True")
        self.assertEqual(sent_request.body["disable_notification"], "False")

    @patch("bot.handlers.comments.is_comment_rate_limit_exceeded", return_value=True)
    def test_rejects_rate_limited_user(self, mock_rate_limit):
        """Should reject user who exceeded rate limit"""
        comment_url = f"https://vas3k.club/post/{self.post.slug}/#comment-{self.comment.id}"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=comment_url,
        )

        # Register route for sendMessage
        self.server.add_route(
            self.REPLY_TEXT_PATH,
            '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}'
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="This is my reply",
            reply_to_text="💬 Original comment",
            reply_to_entities=[entity],
        )
        context = MagicMock()

        reply_to_comment(update, context)

        # Verify no comment was created
        new_comment = Comment.objects.filter(post=self.post, reply_to=self.comment).first()
        self.assertIsNone(new_comment)

        # Verify error message was sent
        send_message_requests = [r for r in self.server.requests_received if r.path == self.REPLY_TEXT_PATH]
        self.assertEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertEqual(sent_request.body["text"], "🙅‍♂️ Извините, вы комментировали слишком часто и достигли дневного лимита")
        self.assertEqual(sent_request.body["disable_notification"], "False")


class CommentToPostTest(BaseTelegramTest, TestCase):
    """Test the comment_to_post handler"""

    tags = {"telegram", "telegram_bot"}

    REPLY_TEXT_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            slug="test-post",
            title="Test Post",
            text="Test content",
            visibility=Post.VISIBILITY_EVERYWHERE,
        )

        # Mock functions
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.rate_limit_patch = patch("bot.handlers.comments.is_comment_rate_limit_exceeded", return_value=False)
        self.async_task_patch = patch("bot.handlers.comments.async_task")
        self.update_counters_patch = patch("bot.handlers.comments.Comment.update_post_counters")
        self.increment_unread_patch = patch("bot.handlers.comments.PostView.increment_unread_comments")
        self.register_view_patch = patch("bot.handlers.comments.PostView.register_view")
        self.update_index_patch = patch("bot.handlers.comments.SearchIndex.update_comment_index")
        self.create_links_patch = patch("bot.handlers.comments.LinkedPost.create_links_from_text")
        self.cached_users_patch = patch("bot.decorators.cached_telegram_users", return_value={str(self.user.telegram_id): self.user.id})

        self.close_old_connections_patch.start()
        self.rate_limit_patch.start()
        self.async_task_patch.start()
        self.update_counters_patch.start()
        self.increment_unread_patch.start()
        self.register_view_patch.start()
        self.update_index_patch.start()
        self.create_links_patch.start()
        self.cached_users_patch.start()

    def tearDown(self):
        super().tearDown()
        Comment.objects.filter(post=self.post).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()
        self.close_old_connections_patch.stop()
        self.rate_limit_patch.stop()
        self.async_task_patch.stop()
        self.update_counters_patch.stop()
        self.increment_unread_patch.stop()
        self.register_view_patch.stop()
        self.update_index_patch.stop()
        self.create_links_patch.stop()
        self.cached_users_patch.stop()

    @override_settings(APP_HOST="https://vas3k.club")
    def test_creates_top_level_comment(self):
        """Should create a top-level comment on post"""
        post_url = f"https://vas3k.club/post/{self.post.slug}/"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=post_url,
        )

        long_text = "This is my comment on the post. " * 5  # Make it longer than MIN_COMMENT_LEN

        # Register route for sendMessage - we'll check the exact body after
        self.server.add_route(
            self.REPLY_TEXT_PATH,
            '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}'
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text=long_text,
            reply_to_text="📝 Post title...",
            reply_to_entities=[entity],
        )
        context = MagicMock()

        comment_to_post(update, context)

        # Verify comment was created
        new_comment = Comment.objects.filter(post=self.post, reply_to=None).first()
        self.assertIsNotNone(new_comment)
        self.assertEqual(new_comment.author, self.user)
        self.assertEqual(new_comment.text, long_text)

        # Now we know the comment ID, verify the exact message sent
        # The handler uses settings.APP_HOST which is http://127.0.0.1:8000 in tests
        expected_url = f"http://127.0.0.1:8000/post/{self.post.slug}/comment/{new_comment.id}/"
        expected_text = f'➜ <a href="{expected_url}">Отвечено</a> 👍'

        send_message_requests = [r for r in self.server.requests_received if r.path == self.REPLY_TEXT_PATH]
        self.assertEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertEqual(sent_request.body["text"], expected_text)
        self.assertEqual(sent_request.body["parse_mode"], "HTML")
        self.assertEqual(sent_request.body["disable_web_page_preview"], "True")
        self.assertEqual(sent_request.body["disable_notification"], "False")

    def test_rejects_short_comment(self):
        """Should reject comments shorter than MIN_COMMENT_LEN"""
        post_url = f"https://vas3k.club/post/{self.post.slug}/"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=post_url,
        )

        # Register route for sendMessage
        self.server.add_route(
            self.REPLY_TEXT_PATH,
            '{"ok": true, "result": {"message_id": 123456, "date": 1770677952, "chat": {"id": 12345, "type": "private"}}}'
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Short",  # Less than 40 chars
            reply_to_text="📝 Post title...",
            reply_to_entities=[entity],
        )
        context = MagicMock()

        comment_to_post(update, context)

        # Verify no comment was created
        new_comment = Comment.objects.filter(post=self.post, reply_to=None).first()
        self.assertIsNone(new_comment)

        # Verify error message was sent
        send_message_requests = [r for r in self.server.requests_received if r.path == self.REPLY_TEXT_PATH]
        self.assertEqual(len(send_message_requests), 1)

        sent_request = send_message_requests[0]
        self.assertEqual(sent_request.body["chat_id"], "12345")
        self.assertEqual(sent_request.body["text"], "😋 Твой коммент слишком короткий. Не буду постить его в Клуб, пускай остается в чате")
        self.assertEqual(sent_request.body["disable_notification"], "False")
