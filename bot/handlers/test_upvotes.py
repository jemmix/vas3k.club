"""Tests for bot/handlers/upvotes.py handlers."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from telegram.ext import CallbackContext

from django.test import TestCase

from bot.handlers.upvotes import upvote_comment, upvote_post, upvote
from bot.test_helpers import (
    create_test_user,
    create_callback_query_update,
    create_reply_update,
    ANSWER_CALLBACK_QUERY_RESPONSE,
    SEND_MESSAGE_RESPONSE,
)
from comments.models import Comment, CommentVote
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post
from posts.models.votes import PostVote


class UpvoteCommentTest(BaseTelegramTest, TestCase):
    """Test the upvote_comment callback handler"""

    tags = {"telegram", "telegram_bot"}

    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
        )
        self.comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Test comment",
        )

        # Mock close_old_connections from common.py (called by get_club_user)
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

    def tearDown(self):
        super().tearDown()
        CommentVote.objects.filter(comment=self.comment).delete()
        Comment.objects.filter(id=self.comment.id).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.user.delete()
        self.close_old_connections_patch.stop()

    async def test_upvote_comment_success(self):
        """Should create new upvote and show success message"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"upvote_comment:{self.comment.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "Комментарий заплюсован 👍",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await upvote_comment(update, context)

        # Verify vote was created
        vote_exists = await CommentVote.objects.filter(
            user=self.user,
            comment=self.comment
        ).aexists()
        self.assertTrue(vote_exists)

    async def test_upvote_comment_already_upvoted(self):
        """Should show already upvoted message when voting twice"""
        # Create existing vote
        await CommentVote.objects.acreate(
            user=self.user,
            comment=self.comment,
            post=self.post,
        )

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"upvote_comment:{self.comment.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "Вы уже плюсовали этот комментарий",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await upvote_comment(update, context)

    async def test_upvote_comment_not_found(self):
        """Should return None when comment doesn't exist"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data="upvote_comment:00000000-0000-0000-0000-000000000000",
        )
        context = MagicMock(spec=CallbackContext)

        result = await upvote_comment(update, context)
        self.assertIsNone(result)

    async def test_upvote_comment_no_user(self):
        """Should return None when user is not found"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=999999,  # Non-existent user
            chat_id=12345,
            data=f"upvote_comment:{self.comment.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "☝️ Привяжи бота к профилю, братишка",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        result = await upvote_comment(update, context)
        self.assertIsNone(result)


class UpvotePostTest(BaseTelegramTest, TestCase):
    """Test the upvote_post callback handler"""

    tags = {"telegram", "telegram_bot"}

    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
        )

        # Mock close_old_connections from common.py (called by get_club_user)
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

    def tearDown(self):
        super().tearDown()
        PostVote.objects.filter(post=self.post).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.user.delete()
        self.close_old_connections_patch.stop()

    async def test_upvote_post_success(self):
        """Should create new upvote and show success message"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"upvote_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "Пост заплюсован 👍",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await upvote_post(update, context)

        # Verify vote was created
        vote_exists = await PostVote.objects.filter(
            user=self.user,
            post=self.post
        ).aexists()
        self.assertTrue(vote_exists)

    async def test_upvote_post_already_upvoted(self):
        """Should show already upvoted message when voting twice"""
        # Create existing vote
        await PostVote.objects.acreate(
            user=self.user,
            post=self.post,
        )

        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data=f"upvote_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "Вы уже плюсовали этот пост",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        await upvote_post(update, context)

    async def test_upvote_post_not_found(self):
        """Should return None when post doesn't exist"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data="upvote_post:00000000-0000-0000-0000-000000000000",
        )
        context = MagicMock(spec=CallbackContext)

        result = await upvote_post(update, context)
        self.assertIsNone(result)

    async def test_upvote_post_no_user(self):
        """Should return None when user is not found"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=999999,  # Non-existent user
            chat_id=12345,
            data=f"upvote_post:{self.post.id}",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "☝️ Привяжи бота к профилю, братишка",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            ),
        ])

        result = upvote_post(update, context)
        self.assertIsNone(result)


class UpvoteReplyTest(BaseTelegramTest, TestCase):
    """Test the upvote reply handler (routes based on emoji)"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.author = create_test_user()
        self.post = Post.objects.create(
            author=self.author,
            slug="test-post",
            title="Test Post",
            text="Test content",
        )
        self.comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Test comment",
        )

        # Mock close_old_connections from common.py (called by get_club_user)
        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

        # Mock cached_telegram_users for @is_club_member decorator
        self.cached_users_patch = patch("bot.decorators.cached_telegram_users")
        self.mock_cached_users = self.cached_users_patch.start()
        self.mock_cached_users.return_value = {"111": self.user}

        # Mock get_club_comment and get_club_post (async functions)
        self.get_club_comment_patch = patch("bot.handlers.upvotes.get_club_comment", new_callable=AsyncMock)
        self.get_club_post_patch = patch("bot.handlers.upvotes.get_club_post", new_callable=AsyncMock)

        self.mock_get_club_comment = self.get_club_comment_patch.start()
        self.mock_get_club_post = self.get_club_post_patch.start()

    def tearDown(self):
        super().tearDown()
        CommentVote.objects.filter(comment=self.comment).delete()
        PostVote.objects.filter(post=self.post).delete()
        Comment.objects.filter(id=self.comment.id).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.author.delete()
        self.user.delete()
        self.close_old_connections_patch.stop()
        self.cached_users_patch.stop()
        self.get_club_comment_patch.stop()
        self.get_club_post_patch.stop()

    async def test_upvote_comment_via_reply(self):
        """Should upvote comment when replying to comment message"""
        self.mock_get_club_comment.return_value = self.comment

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="+1",
            reply_to_text="💬 Test comment text here",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "➜ Заплюсовано 👍",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await upvote(update, context)

        # Verify vote was created
        vote_exists = await CommentVote.objects.filter(
            user=self.user,
            comment=self.comment
        ).aexists()
        self.assertTrue(vote_exists)

    async def test_upvote_comment_already_upvoted(self):
        """Should show already upvoted message for duplicate comment upvote"""
        self.mock_get_club_comment.return_value = self.comment

        # Create existing vote
        await CommentVote.objects.acreate(
            user=self.user,
            comment=self.comment,
            post=self.post,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="+1",
            reply_to_text="💬 Test comment text here",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "➜ Ты уже плюсовал, поц",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await upvote(update, context)

    async def test_upvote_post_via_reply(self):
        """Should upvote post when replying to post message"""
        self.mock_get_club_post.return_value = self.post

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="+1",
            reply_to_text="📝 Test post title",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "➜ Заплюсовано 👍",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await upvote(update, context)

        # Verify vote was created
        vote_exists = await PostVote.objects.filter(
            user=self.user,
            post=self.post
        ).aexists()
        self.assertTrue(vote_exists)

    async def test_upvote_post_already_upvoted(self):
        """Should show already upvoted message for duplicate post upvote"""
        self.mock_get_club_post.return_value = self.post

        # Create existing vote
        await PostVote.objects.acreate(
            user=self.user,
            post=self.post,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="+1",
            reply_to_text="📝 Test post title",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "➜ Ты уже плюсовал, поц",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        await upvote(update, context)

    async def test_upvote_not_a_reply(self):
        """Should return None when message is not a reply"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            data="some_data",
        )
        context = MagicMock(spec=CallbackContext)

        result = await upvote(update, context)
        self.assertIsNone(result)

    async def test_upvote_no_user(self):
        """Should return None when user is not found"""
        # Mock cached users to allow past the decorator
        self.mock_cached_users.return_value = {"999999": None}

        update = create_reply_update(
            bot=self.bot,
            telegram_id=999999,  # Non-existent user
            chat_id=12345,
            text="+1",
            reply_to_text="💬 Test comment",
        )
        context = MagicMock(spec=CallbackContext)

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "😐 Привяжи <a href=\"https://vas3k.club/user/me/edit/bot/\">бота</a> к профилю, братишка",
                        "parse_mode": "HTML",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            ),
        ])

        result = upvote(update, context)
        self.assertIsNone(result)
