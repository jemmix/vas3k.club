from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase

from notifications.telegram.common import ADMIN_CHAT, VIBES_CHAT
from comments.models import Comment
from posts.models.post import Post
from users.models.user import User


class NotifyModeratorsOnMentionTest(TestCase):
    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(
            full_name="Commenter",
            email="commenter@example.com",
            membership_started_at=datetime.utcnow(),
            membership_expires_at=datetime.utcnow() + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        self.post = Post.objects.create(
            author=self.user,
            title="Test Post",
            text="Some post text",
        )
        self.comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="@moderator please look at this",
        )

    @patch("notifications.telegram.moderation.render_html_message")
    @patch("notifications.telegram.moderation.send_telegram_message")
    async def test_sends_to_admin_and_vibes_chats(self, mock_send_msg, mock_render):
        from notifications.telegram.moderation import notify_moderators_on_mention

        mock_render.return_value = "<b>Moderator mention</b>"

        notify_moderators_on_mention(self.comment)

        self.assertEqual(mock_send_msg.call_count, 2)

        chats_called = [call.kwargs["chat"] for call in mock_send_msg.call_args_list]
        self.assertIn(ADMIN_CHAT, chats_called)
        self.assertIn(VIBES_CHAT, chats_called)

    @patch("notifications.telegram.moderation.render_html_message")
    @patch("notifications.telegram.moderation.send_telegram_message")
    async def test_renders_template_with_comment(self, mock_send_msg, mock_render):
        from notifications.telegram.moderation import notify_moderators_on_mention

        mock_render.return_value = "<b>rendered</b>"

        notify_moderators_on_mention(self.comment)

        mock_render.assert_called_with("moderator_mention.html", comment=self.comment)
