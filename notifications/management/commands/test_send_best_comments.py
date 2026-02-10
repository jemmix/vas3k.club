"""Tests for notifications/management/commands/send_best_comments.py command."""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from badges.models import Badge, UserBadge
from bot.test_helpers import create_test_user
from comments.models import Comment
from notifications.telegram.tests import BaseNotificationTest
from posts.models.post import Post
from users.models.user import User


class SendBestCommentsCommandTest(BaseNotificationTest, TestCase):
    """Test the send_best_comments management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Patch send_telegram_message in the command module
        self.cmd_send_msg_patcher = patch(
            "notifications.management.commands.send_best_comments.send_telegram_message"
        )
        self.mock_send_msg = self.cmd_send_msg_patcher.start()

        # Create test user and post
        self.user = create_test_user(email="commenter@example.com")
        self.post = Post.objects.create(
            author=self.user,
            type=Post.TYPE_POST,
            title="Test Post",
            text="Content",
            moderation_status=Post.MODERATION_APPROVED,
        )

        # Create comment with high upvotes (should be sent)
        self.best_comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Great comment",
            upvotes=50,  # Above MIN_UPVOTES (30)
            created_at=datetime.utcnow() - timedelta(days=1),
        )

        # Create comment with low upvotes (should be skipped)
        self.low_upvote_comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Low upvote comment",
            upvotes=10,  # Below MIN_UPVOTES (30)
            created_at=datetime.utcnow() - timedelta(days=1),
        )

        # Create old comment (should be skipped)
        self.old_comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Old comment",
            upvotes=50,
            created_at=datetime.utcnow() - timedelta(days=10),  # Outside TIME_INTERVAL (3 days)
        )

    def tearDown(self):
        self.cmd_send_msg_patcher.stop()
        super().tearDown()
        Comment.objects.filter(id__in=[
            self.best_comment.id,
            self.low_upvote_comment.id,
            self.old_comment.id,
        ]).delete()
        self.post.delete()
        self.user.delete()

    def test_sends_best_comment_to_channel(self):
        """Should send best comment to telegram channel"""
        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify telegram message sent once
        self.assertEqual(self.mock_send_msg.call_count, 1)

        # Verify correct chat ID (TELEGRAM_CHANNEL_ID = -1001814814883)
        call_args = self.mock_send_msg.call_args[1]
        self.assertEqual(call_args["chat"].id, -1001814814883)

        # Verify comment metadata was set
        self.best_comment.refresh_from_db()
        self.assertTrue(self.best_comment.metadata.get("in_best_comments"))

        # Verify output
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn(f"Comment {self.best_comment.id} +50", output)

    def test_skips_already_sent_comments(self):
        """Should skip comments already marked as sent"""
        # Mark comment as already sent
        self.best_comment.metadata = {"in_best_comments": True}
        self.best_comment.save(update_fields=["metadata"])

        # Also mark other comments to ensure clean state
        self.low_upvote_comment.metadata = {"in_best_comments": True}
        self.low_upvote_comment.save(update_fields=["metadata"])
        self.old_comment.metadata = {"in_best_comments": True}
        self.old_comment.save(update_fields=["metadata"])

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify no telegram message sent
        self.assertEqual(self.mock_send_msg.call_count, 0)

        # Verify output
        output = out.getvalue()
        self.assertIn("Done 🥙", output)

    def test_only_sends_one_comment(self):
        """Should only send one comment due to break statement"""
        # Create second best comment
        second_comment = Comment.objects.create(
            author=self.user,
            post=self.post,
            text="Another great comment",
            upvotes=60,
            created_at=datetime.utcnow() - timedelta(hours=12),
        )

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify only one telegram message sent (due to break)
        self.assertEqual(self.mock_send_msg.call_count, 1)

        # Cleanup - use queryset delete to avoid deleted_by requirement
        Comment.objects.filter(id=second_comment.id).delete()

    def test_handles_telegram_error(self):
        """Should handle telegram send errors and continue"""
        self.mock_send_msg.side_effect = Exception("Telegram API error")

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify command completed despite error
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn("Error sending the message", output)

        # Verify metadata was still set
        self.best_comment.refresh_from_db()
        self.assertTrue(self.best_comment.metadata.get("in_best_comments"))

    def test_includes_comments_with_badges(self):
        """Should include comments that have new badges"""
        # Create badge and user badge for a low-upvote comment
        badge = Badge.objects.create(
            code="testbadge",
            title="Test Badge",
        )
        user_badge = UserBadge.objects.create(
            to_user=self.user,
            badge=badge,
            comment=self.low_upvote_comment,
            created_at=datetime.utcnow() - timedelta(hours=6),
        )

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify message was sent (even though upvotes are low, badge makes it eligible)
        self.assertGreaterEqual(self.mock_send_msg.call_count, 1)

        # Cleanup
        UserBadge.objects.filter(badge=badge, to_user=self.user).delete()
        Badge.objects.filter(code="testbadge").delete()

    def test_respects_post_moderation_status(self):
        """Should only include comments on approved posts"""
        # Create comment on pending post
        pending_post = Post.objects.create(
            author=self.user,
            type=Post.TYPE_POST,
            title="Pending Post",
            text="Content",
            moderation_status=Post.MODERATION_PENDING,
        )
        pending_comment = Comment.objects.create(
            author=self.user,
            post=pending_post,
            text="Comment on pending post",
            upvotes=50,
            created_at=datetime.utcnow() - timedelta(hours=6),
        )

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify only best_comment (on approved post) was sent
        self.assertEqual(self.mock_send_msg.call_count, 1)

        # Cleanup - use queryset delete to avoid deleted_by requirement
        Comment.objects.filter(id=pending_comment.id).delete()
        Post.objects.filter(id=pending_post.id).delete()

    def test_handles_no_eligible_comments(self):
        """Should handle case when there are no eligible comments"""
        # Mark all comments as sent
        self.best_comment.metadata = {"in_best_comments": True}
        self.best_comment.save(update_fields=["metadata"])
        self.low_upvote_comment.metadata = {"in_best_comments": True}
        self.low_upvote_comment.save(update_fields=["metadata"])
        self.old_comment.metadata = {"in_best_comments": True}
        self.old_comment.save(update_fields=["metadata"])

        out = StringIO()
        call_command("send_best_comments", stdout=out)

        # Verify no message sent
        self.assertEqual(self.mock_send_msg.call_count, 0)

        # Verify command completed successfully
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
