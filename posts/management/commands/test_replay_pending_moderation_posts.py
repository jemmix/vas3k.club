"""Tests for posts/management/commands/replay_pending_moderation_posts.py command."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from bot.test_helpers import create_test_user
from notifications.telegram.tests import BaseNotificationTest
from posts.models.post import Post


class ReplayPendingModerationPostsCommandTest(BaseNotificationTest, TestCase):
    """Test the replay_pending_moderation_posts management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Create test users
        self.author = create_test_user(email="author@example.com", telegram_id="111")

        # Create test posts with different moderation statuses
        self.pending_post1 = Post.objects.create(
            author=self.author,
            type=Post.TYPE_POST,
            title="Pending Post 1",
            text="Content 1",
            moderation_status=Post.MODERATION_PENDING,
        )
        self.pending_post2 = Post.objects.create(
            author=self.author,
            type=Post.TYPE_POST,
            title="Pending Post 2",
            text="Content 2",
            moderation_status=Post.MODERATION_PENDING,
        )
        self.approved_post = Post.objects.create(
            author=self.author,
            type=Post.TYPE_POST,
            title="Approved Post",
            text="Content",
            moderation_status=Post.MODERATION_APPROVED,
        )

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(slug__in=[
            self.pending_post1.slug,
            self.pending_post2.slug,
            self.approved_post.slug,
        ]).delete()
        self.author.delete()

    @patch("posts.management.commands.replay_pending_moderation_posts.send_published_post_to_moderators")
    def test_sends_all_pending_posts_to_moderators(self, mock_send):
        """Should call send_published_post_to_moderators for each pending post"""
        out = StringIO()
        call_command("replay_pending_moderation_posts", stdout=out)

        # Verify send_published_post_to_moderators was called twice
        self.assertEqual(mock_send.call_count, 2)

        # Verify it was called with the pending posts
        called_post_ids = {call[1]["post"].id for call in mock_send.call_args_list}
        self.assertEqual(called_post_ids, {self.pending_post1.id, self.pending_post2.id})

        # Verify approved post was not sent
        self.assertNotIn(self.approved_post.id, called_post_ids)

        # Verify output
        self.assertIn("Done 🥙", out.getvalue())

    @patch("posts.management.commands.replay_pending_moderation_posts.send_published_post_to_moderators")
    def test_handles_no_pending_posts(self, mock_send):
        """Should handle case when there are no pending posts"""
        # Mark all posts as approved
        Post.objects.filter(moderation_status=Post.MODERATION_PENDING).update(
            moderation_status=Post.MODERATION_APPROVED
        )

        out = StringIO()
        call_command("replay_pending_moderation_posts", stdout=out)

        # Verify send_published_post_to_moderators was not called
        self.assertEqual(mock_send.call_count, 0)

        # Verify output
        self.assertIn("Done 🥙", out.getvalue())

