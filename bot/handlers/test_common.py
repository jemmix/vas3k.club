"""Tests for bot/handlers/common.py helper functions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from django.test import TestCase
from telegram import MessageEntity
from telegram.ext import CallbackContext

from bot.handlers.common import get_club_user, get_club_comment, get_club_post
from bot.test_helpers import (
    create_test_user,
    create_message_update,
    create_callback_query_update,
    create_reply_update,
    SEND_MESSAGE_RESPONSE,
    ANSWER_CALLBACK_QUERY_RESPONSE,
)
from comments.models import Comment
from notifications.telegram.tests import BaseTelegramTest, ExpectedRequest, Request
from posts.models.post import Post
from users.models.user import User


class GetClubUserTest(BaseTelegramTest, TestCase):
    """Test the get_club_user helper function"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"
    ANSWER_CALLBACK_QUERY_PATH = f"/{BaseTelegramTest.TOKEN}/answerCallbackQuery"

    def setUp(self):
        super().setUp()
        self.active_user = create_test_user(telegram_id="111")
        self.banned_user = create_test_user(
            telegram_id="222",
            is_banned_until=datetime.now(timezone.utc) + timedelta(days=365),
        )
        # User is not approved (not a member)
        self.inactive_user = create_test_user(
            telegram_id="333",
            moderation_status=User.MODERATION_STATUS_INTRO,
        )

        self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
        self.close_old_connections_patch.start()

    def tearDown(self):
        super().tearDown()
        self.active_user.delete()
        self.banned_user.delete()
        self.inactive_user.delete()
        self.close_old_connections_patch.stop()

    def test_returns_active_user(self):
        """Should return user for active member"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Test",
        )

        user = get_club_user(update)

        self.assertIsNotNone(user)
        self.assertEqual(user.id, self.active_user.id)

    def test_rejects_unknown_user_via_message(self):
        """Should send reply_text for unknown user via message"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=999,
            chat_id=12345,
            text="Test",
        )

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
            )
        ])

        user = get_club_user(update)

        self.assertIsNone(user)

    def test_rejects_unknown_user_via_callback_query(self):
        """Should send callback_query.answer for unknown user via callback"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=999,
            chat_id=12345,
            data="test_callback",
        )

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
            )
        ])

        user = get_club_user(update)

        self.assertIsNone(user)

    def test_rejects_banned_user_via_message(self):
        """Should reject banned user via message"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=12345,
            text="Test",
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🙈 Ты в бане, мы больше не дружим",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        user = get_club_user(update)

        self.assertIsNone(user)

    def test_rejects_banned_user_via_callback_query(self):
        """Should reject banned user via callback_query"""
        update = create_callback_query_update(
            bot=self.bot,
            telegram_id=222,
            chat_id=12345,
            data="test_callback",
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.ANSWER_CALLBACK_QUERY_PATH,
                    {
                        "callback_query_id": "callback_query_id",
                        "text": "🙈 Ты в бане, мы больше не дружим",
                    },
                ),
                ANSWER_CALLBACK_QUERY_RESPONSE(),
            )
        ])

        user = get_club_user(update)

        self.assertIsNone(user)

    def test_rejects_inactive_user_via_message(self):
        """Should reject inactive user via message"""
        update = create_message_update(
            bot=self.bot,
            telegram_id=333,
            chat_id=12345,
            text="Test",
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "😣 Твой профиль в Клубе неактивен. Плоти долор!",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        user = get_club_user(update)

        self.assertIsNone(user)


class GetClubCommentTest(BaseTelegramTest, TestCase):
    """Test the get_club_comment helper function"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            title="Test Post",
            text="Test content",
        )
        self.comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Test comment",
        )

    def tearDown(self):
        super().tearDown()
        # Use direct DB deletion to avoid custom delete() logic
        Comment.objects.filter(id=self.comment.id).delete()
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()

    def test_finds_comment_from_url_entity(self):
        """Should find comment from text_link entity"""
        comment_url = f"https://vas3k.club/post/test-post/#comment-{self.comment.id}"

        # Create entity with text_link to comment
        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=comment_url,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="👍",
            reply_to_text="Original comment",
            reply_to_entities=[entity],
        )

        comment = get_club_comment(update)

        self.assertIsNotNone(comment)
        self.assertEqual(comment.id, self.comment.id)

    def test_returns_none_when_no_url_entity(self):
        """Should return None when no URL entity found"""
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="👍",
            reply_to_text="Original comment",
        )

        comment = get_club_comment(update)

        self.assertIsNone(comment)

    def test_sends_message_when_comment_deleted(self):
        """Should send message when comment ID not found"""
        # Use a valid UUID that doesn't exist
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        comment_url = f"https://vas3k.club/post/test-post/#comment-{fake_uuid}"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=comment_url,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="👍",
            reply_to_text="Original comment",
            reply_to_entities=[entity],
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": f"🤨 Коммент '{fake_uuid}' был удален или куда-то делся",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        comment = get_club_comment(update)

        self.assertIsNone(comment)


class GetClubPostTest(BaseTelegramTest, TestCase):
    """Test the get_club_post helper function"""

    tags = {"telegram", "telegram_bot"}

    SEND_MESSAGE_PATH = f"/{BaseTelegramTest.TOKEN}/sendMessage"

    def setUp(self):
        super().setUp()
        self.user = create_test_user(telegram_id="111")
        self.post = Post.objects.create(
            author=self.user,
            slug="test-post-slug",
            title="Test Post",
            text="Test content",
            visibility=Post.VISIBILITY_EVERYWHERE,
        )

    def tearDown(self):
        super().tearDown()
        # Use direct DB deletion to avoid custom delete() logic
        Post.objects.filter(id=self.post.id).delete()
        self.user.delete()

    def test_finds_post_from_url_entity(self):
        """Should find post from text_link entity"""
        post_url = f"https://vas3k.club/post/{self.post.slug}/"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=post_url,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Comment on post",
            reply_to_text="Original post message",
            reply_to_entities=[entity],
        )

        post = get_club_post(update)

        self.assertIsNotNone(post)
        self.assertEqual(post.id, self.post.id)

    def test_returns_none_when_no_url_entity(self):
        """Should return None when no URL entity found"""
        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Comment",
            reply_to_text="Original post",
        )

        post = get_club_post(update)

        self.assertIsNone(post)

    def test_sends_message_when_post_not_found(self):
        """Should send message when post not found"""
        post_url = "https://vas3k.club/post/nonexistent-post/"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=post_url,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Comment",
            reply_to_text="Original post",
            reply_to_entities=[entity],
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Пост был удален, скрыт или украден, сорян",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        post = get_club_post(update)

        self.assertIsNone(post)

    def test_sends_message_when_post_not_commentable(self):
        """Should send message when post is not commentable"""
        # Make post non-commentable
        self.post.is_commentable = False
        self.post.save()

        post_url = f"https://vas3k.club/post/{self.post.slug}/"

        entity = MessageEntity(
            type="text_link",
            offset=0,
            length=10,
            url=post_url,
        )

        update = create_reply_update(
            bot=self.bot,
            telegram_id=111,
            chat_id=12345,
            text="Comment",
            reply_to_text="Original post",
            reply_to_entities=[entity],
        )

        self.server.expect_requests([
            ExpectedRequest(
                Request(
                    "POST",
                    self.SEND_MESSAGE_PATH,
                    {
                        "chat_id": "12345",
                        "text": "🤨 Пост был удален, скрыт или украден, сорян",
                        "disable_notification": "False",
                    },
                ),
                SEND_MESSAGE_RESPONSE(),
            )
        ])

        post = get_club_post(update)

        self.assertIsNone(post)
