"""Tests for bot/handlers/top.py handlers."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from telegram.ext import CallbackContext

from django.test import TestCase

from bot.handlers.top import command_top
from bot.test_helpers import (
    create_test_user,
    create_command_update,
    SEND_MESSAGE_RESPONSE,
)
from comments.models import Comment
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post


class CommandTopTest(BaseTelegramTest, TestCase):
    """Test the command_top handler"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")

        # Create test posts with different types and upvotes
        now = datetime.now(timezone.utc)

        # Top post (high upvotes, recent)
        self.top_post = Post.objects.create(
            author=self.user,
            slug="top-post",
            title="Top Post",
            text="Top content",
            type=Post.TYPE_POST,
            published_at=now - timedelta(hours=12),
            moderation_status=Post.MODERATION_APPROVED,
            visibility=Post.VISIBILITY_EVERYWHERE,
            upvotes=100,
        )

        # Hot post (medium upvotes, very recent)
        self.hot_post = Post.objects.create(
            author=self.user,
            slug="hot-post",
            title="Hot Post",
            text="Hot content",
            type=Post.TYPE_POST,
            published_at=now - timedelta(hours=1),
            moderation_status=Post.MODERATION_APPROVED,
            visibility=Post.VISIBILITY_EVERYWHERE,
            upvotes=10,
            hotness=999,
        )

        # Top intro
        self.top_intro = Post.objects.create(
            author=self.user,
            slug=f"intro-{self.user.slug}",  # Intro slugs are based on user slug
            title="Top Intro",
            text="Intro content",
            type=Post.TYPE_INTRO,
            published_at=now - timedelta(hours=12),
            moderation_status=Post.MODERATION_APPROVED,
            visibility=Post.VISIBILITY_EVERYWHERE,
            upvotes=50,
        )

        # Top comment
        self.comment_post = Post.objects.create(
            author=self.user,
            slug="comment-post",
            title="Comment Post",
            text="Post for comment",
            type=Post.TYPE_POST,
            published_at=now - timedelta(hours=12),
            moderation_status=Post.MODERATION_APPROVED,
            visibility=Post.VISIBILITY_EVERYWHERE,
        )

        self.top_comment = Comment.objects.create(
            author=self.user,
            post=self.comment_post,
            text="Top comment",
            upvotes=75,
        )

        # Mock close_old_connections
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

        # Mock cached_telegram_users for @is_club_member decorator
        self.cached_users_patch = patch("bot.decorators.cached_telegram_users")
        self.mock_cached_users = self.cached_users_patch.start()
        self.mock_cached_users.return_value = {str(self.user.telegram_id): self.user.id}

    def tearDown(self):
        super().tearDown()
        Comment.objects.filter(post=self.comment_post).delete()
        Post.objects.filter(id__in=[
            self.top_post.id,
            self.hot_post.id,
            self.top_intro.id,
            self.comment_post.id,
        ]).delete()
        self.user.delete()
        self.close_old_connections_patch.stop()
        self.cached_users_patch.stop()

    @patch("bot.handlers.top.render_html_message")
    async def test_sends_top_content(self, mock_render):
        """Should send top posts, hot posts, intros, and comments"""
        # Mock template rendering
        mock_render.return_value = "Rendered top content message"

        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/top",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "Rendered top content message",
                        "parse_mode": "HTML",
                        "disable_web_page_preview": "True",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_top(update, context)

        # Verify template was called with correct parameters
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        self.assertEqual(call_kwargs["template"], "top.html")
        # Verify the handler passed querysets with expected types
        self.assertIsNotNone(call_kwargs["top_posts"])
        self.assertIsNotNone(call_kwargs["hot_posts"])
        self.assertIsNotNone(call_kwargs["top_intros"])
        # Verify our test comment is included
        self.assertEqual(call_kwargs["top_comment"], self.top_comment)

    @patch("bot.handlers.top.Comment.visible_objects")
    @patch("bot.handlers.top.Post.visible_objects")
    @patch("bot.handlers.top.render_html_message")
    async def test_handles_no_content(self, mock_render, mock_post_visible, mock_comment_visible):
        """Should send message even when no top content found"""
        # Mock empty querysets
        mock_post_qs = MagicMock()
        mock_post_qs.filter.return_value = mock_post_qs
        mock_post_qs.exclude.return_value = mock_post_qs
        mock_post_qs.select_related.return_value = mock_post_qs
        mock_post_qs.order_by.return_value = mock_post_qs
        mock_post_qs.__getitem__ = MagicMock(return_value=[])
        mock_post_visible.return_value = mock_post_qs

        mock_comment_qs = MagicMock()
        mock_comment_qs.filter.return_value = mock_comment_qs
        mock_comment_qs.exclude.return_value = mock_comment_qs
        mock_comment_qs.select_related.return_value = mock_comment_qs
        mock_comment_qs.order_by.return_value = mock_comment_qs
        mock_comment_qs.first.return_value = None
        mock_comment_visible.return_value = mock_comment_qs

        # Mock template rendering with empty data
        mock_render.return_value = "No top content available message"

        update = create_command_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            command="/top",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "No top content available message",
                        "parse_mode": "HTML",
                        "disable_web_page_preview": "True",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await command_top(update, context)

        # Verify template was called with empty data
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        self.assertEqual(call_kwargs["template"], "top.html")
        self.assertEqual(list(call_kwargs["top_posts"]), [])
        self.assertEqual(list(call_kwargs["hot_posts"]), [])
        self.assertEqual(list(call_kwargs["top_intros"]), [])
        self.assertIsNone(call_kwargs["top_comment"])
