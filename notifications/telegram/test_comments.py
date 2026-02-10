from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, override_settings

from comments.models import Comment
from notifications.telegram.comments import notify_on_comment_created
from notifications.telegram.common import Chat, CLUB_ONLINE
from posts.models.post import Post
from posts.models.subscriptions import PostSubscription
from rooms.models import Room
from users.models.friends import Friend
from users.models.mute import UserMuted
from users.models.user import User


class NotifyOnCommentCreatedTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        now = datetime.utcnow()
        expires = now + timedelta(days=30)

        self.author = User.objects.create(
            slug="author",
            full_name="Author User",
            email="author@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="100",
        )
        self.subscriber_user = User.objects.create(
            slug="subscriber",
            full_name="Subscriber User",
            email="subscriber@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="200",
        )
        self.thread_author = User.objects.create(
            slug="threadauthor",
            full_name="Thread Author",
            email="threadauthor@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="300",
        )
        self.mentioned_user = User.objects.create(
            slug="mentioned",
            full_name="Mentioned User",
            email="mentioned@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="400",
        )
        self.friend_user = User.objects.create(
            slug="frienduser",
            full_name="Friend User",
            email="friend@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="500",
        )
        self.muter_user = User.objects.create(
            slug="muter",
            full_name="Muter User",
            email="muter@example.com",
            membership_started_at=now,
            membership_expires_at=expires,
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="600",
        )

        self.post = Post.objects.create(
            author=self.author,
            title="Test Post",
            text="Some text",
            visibility=Post.VISIBILITY_EVERYWHERE,
        )

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_notifies_all_comment_subscribers(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A top-level comment",
        )
        PostSubscription.objects.create(
            user=self.subscriber_user,
            post=self.post,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="200"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_notifies_top_level_only_subscribers_for_top_level_comment(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A top-level comment",
        )
        PostSubscription.objects.create(
            user=self.subscriber_user,
            post=self.post,
            type=PostSubscription.TYPE_TOP_LEVEL_ONLY,
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="200"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_top_level_only_subscribers_for_reply(self, mock_render, mock_send):
        parent_comment = Comment.objects.create(
            author=self.thread_author,
            post=self.post,
            text="Parent comment",
        )
        reply = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A reply",
            reply_to=parent_comment,
        )
        PostSubscription.objects.create(
            user=self.subscriber_user,
            post=self.post,
            type=PostSubscription.TYPE_TOP_LEVEL_ONLY,
        )

        notify_on_comment_created(reply)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="200"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_comment_author_in_subscribers(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A top-level comment",
        )
        PostSubscription.objects.create(
            user=self.author,
            post=self.post,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="100"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_notifies_thread_author_on_reply(self, mock_render, mock_send):
        parent_comment = Comment.objects.create(
            author=self.thread_author,
            post=self.post,
            text="Parent comment",
        )
        reply = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A reply",
            reply_to=parent_comment,
        )

        notify_on_comment_created(reply)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="300"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_thread_author_when_same_as_comment_author(self, mock_render, mock_send):
        parent_comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Parent comment",
        )
        reply = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Replying to myself",
            reply_to=parent_comment,
        )

        notify_on_comment_created(reply)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="100"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_thread_author_already_notified_as_subscriber(self, mock_render, mock_send):
        parent_comment = Comment.objects.create(
            author=self.thread_author,
            post=self.post,
            text="Parent comment",
        )
        reply = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A reply",
            reply_to=parent_comment,
        )
        PostSubscription.objects.create(
            user=self.thread_author,
            post=self.post,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        )

        notify_on_comment_created(reply)

        # thread_author (telegram_id=300) should appear exactly once
        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        count = send_chats.count(Chat(id="300"))
        self.assertEqual(count, 1)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_posts_top_level_to_online_channel(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A top-level comment",
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(CLUB_ONLINE, send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_online_channel_for_reply(self, mock_render, mock_send):
        parent_comment = Comment.objects.create(
            author=self.thread_author,
            post=self.post,
            text="Parent comment",
        )
        reply = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="A reply",
            reply_to=parent_comment,
        )

        notify_on_comment_created(reply)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(CLUB_ONLINE, send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_online_channel_for_draft_post(self, mock_render, mock_send):
        draft_post = Post.objects.create(
            author=self.author,
            title="Draft Post",
            text="Draft text",
            visibility=Post.VISIBILITY_DRAFT,
        )
        comment = Comment.objects.create(
            author=self.author,
            post=draft_post,
            text="Comment on draft",
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(CLUB_ONLINE, send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_posts_to_room_chat(self, mock_render, mock_send):
        room = Room.objects.create(
            slug="testroom",
            title="Test Room",
            color="#ffffff",
            chat_id="999",
            send_new_comments_to_chat=True,
        )
        room_post = Post.objects.create(
            author=self.author,
            title="Room Post",
            text="Text",
            visibility=Post.VISIBILITY_EVERYWHERE,
            room=room,
        )
        comment = Comment.objects.create(
            author=self.author,
            post=room_post,
            text="Comment in room",
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="999"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_room_chat_when_send_disabled(self, mock_render, mock_send):
        room = Room.objects.create(
            slug="quietroom",
            title="Quiet Room",
            color="#000000",
            chat_id="888",
            send_new_comments_to_chat=False,
        )
        room_post = Post.objects.create(
            author=self.author,
            title="Room Post",
            text="Text",
            visibility=Post.VISIBILITY_EVERYWHERE,
            room=room,
        )
        comment = Comment.objects.create(
            author=self.author,
            post=room_post,
            text="Comment in quiet room",
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="888"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_notifies_mentioned_users(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Hey @mentioned check this out",
        )

        notify_on_comment_created(comment)

        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="400"), send_chats)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_skips_mentioned_already_notified(self, mock_render, mock_send):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Hey @subscriber check this out",
        )
        PostSubscription.objects.create(
            user=self.subscriber_user,
            post=self.post,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        )

        notify_on_comment_created(comment)

        # subscriber (telegram_id=200) should appear exactly once (via subscription, not mention)
        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        count = send_chats.count(Chat(id="200"))
        self.assertEqual(count, 1)

    @patch("notifications.telegram.comments.notify_moderators_on_mention")
    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_calls_notify_moderators_on_moderator_mention(self, mock_render, mock_send, mock_notify_mods):
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Hey @moderator please help",
        )

        notify_on_comment_created(comment)

        mock_notify_mods.assert_called_once_with(comment)

    @patch("notifications.telegram.comments.send_telegram_message")
    @patch("notifications.telegram.comments.render_html_message", return_value="<b>html</b>")
    def test_respects_muted_author(self, mock_render, mock_send):
        # muter_user mutes the comment author
        UserMuted.objects.create(
            user_from=self.muter_user,
            user_to=self.author,
        )
        comment = Comment.objects.create(
            author=self.author,
            post=self.post,
            text="Hey @muter check this",
        )
        PostSubscription.objects.create(
            user=self.muter_user,
            post=self.post,
            type=PostSubscription.TYPE_ALL_COMMENTS,
        )

        notify_on_comment_created(comment)

        # muter_user (telegram_id=600) should NOT be notified via subscription or mention
        send_chats = [c.kwargs["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="600"), send_chats)
