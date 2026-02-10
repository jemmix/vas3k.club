"""Tests for users/management/commands/replay_stuck_reviews.py command."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from bot.test_helpers import create_test_user
from notifications.telegram.tests import BaseNotificationTest
from posts.models.post import Post
from users.models.user import User


class ReplayStuckReviewsCommandTest(BaseNotificationTest, TestCase):
    """Test the replay_stuck_reviews management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Create users with different moderation statuses
        self.review_user1 = create_test_user(
            email="review1@example.com",
            telegram_id="111",
            moderation_status=User.MODERATION_STATUS_ON_REVIEW,
        )
        self.review_user2 = create_test_user(
            email="review2@example.com",
            telegram_id="222",
            moderation_status=User.MODERATION_STATUS_ON_REVIEW,
        )
        self.approved_user = create_test_user(
            email="approved@example.com",
            telegram_id="333",
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )

        # Create intro posts for review users
        self.intro1 = Post.objects.create(
            author=self.review_user1,
            type=Post.TYPE_INTRO,
            title="Intro 1",
            text="Intro content 1",
            moderation_status=Post.MODERATION_PENDING,
        )
        self.intro2 = Post.objects.create(
            author=self.review_user2,
            type=Post.TYPE_INTRO,
            title="Intro 2",
            text="Intro content 2",
            moderation_status=Post.MODERATION_PENDING,
        )

    def tearDown(self):
        super().tearDown()
        Post.objects.filter(slug__in=[self.intro1.slug, self.intro2.slug]).delete()
        User.objects.filter(slug__in=[
            self.review_user1.slug,
            self.review_user2.slug,
            self.approved_user.slug,
        ]).delete()

    @patch("users.management.commands.replay_stuck_reviews.notify_profile_needs_review")
    def test_sends_all_stuck_reviews_to_moderators(self, mock_notify):
        """Should call notify_profile_needs_review for each on-review user"""
        out = StringIO()
        call_command("replay_stuck_reviews", stdout=out)

        # Verify notify_profile_needs_review was called twice
        self.assertEqual(mock_notify.call_count, 2)

        # Verify it was called with the review users and their intros
        call_users = {call[0][0].id for call in mock_notify.call_args_list}
        self.assertEqual(call_users, {self.review_user1.id, self.review_user2.id})

        call_intros = {call[0][1].id for call in mock_notify.call_args_list}
        self.assertEqual(call_intros, {self.intro1.id, self.intro2.id})

        # Verify approved user was not notified
        self.assertNotIn(self.approved_user.id, call_users)

        # Verify output
        self.assertIn("Done 🥙", out.getvalue())

    @patch("users.management.commands.replay_stuck_reviews.notify_profile_needs_review")
    def test_handles_no_users_on_review(self, mock_notify):
        """Should handle case when there are no users on review"""
        # Mark all users as approved
        User.objects.filter(moderation_status=User.MODERATION_STATUS_ON_REVIEW).update(
            moderation_status=User.MODERATION_STATUS_APPROVED
        )

        out = StringIO()
        call_command("replay_stuck_reviews", stdout=out)

        # Verify notify_profile_needs_review was not called
        self.assertEqual(mock_notify.call_count, 0)

        # Verify output
        self.assertIn("Done 🥙", out.getvalue())

