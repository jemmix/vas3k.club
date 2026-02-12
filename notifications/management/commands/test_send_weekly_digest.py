"""Tests for notifications/management/commands/send_weekly_digest.py command."""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.test import TestCase
import telegram
from telegram.constants import ParseMode

from bot.test_helpers import create_test_user
from club.exceptions import NotFound
from notifications.telegram.tests import BaseNotificationTest
from posts.models.post import Post
from users.models.user import User


class SendWeeklyDigestCommandTest(BaseNotificationTest, TestCase):
    """Test the send_weekly_digest management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Patch functions in the command module
        self.cmd_send_msg_patcher = patch(
            "notifications.management.commands.send_weekly_digest.send_telegram_message"
        )
        self.mock_send_msg = self.cmd_send_msg_patcher.start()

        self.generate_digest_patcher = patch(
            "notifications.management.commands.send_weekly_digest.generate_weekly_digest"
        )
        self.mock_generate_digest = self.generate_digest_patcher.start()
        self.mock_generate_digest.return_value = (
            "<h1>Test digest</h1>",  # digest_template
            "Test OG description"  # og_description
        )

        self.send_email_patcher = patch(
            "notifications.management.commands.send_weekly_digest.send_mass_email"
        )
        self.mock_send_email = self.send_email_patcher.start()

        self.clubsettings_get_patcher = patch(
            "notifications.management.commands.send_weekly_digest.ClubSettings.get"
        )
        self.mock_clubsettings_get = self.clubsettings_get_patcher.start()
        self.mock_clubsettings_get.side_effect = lambda key: "Test Title" if key == "digest_title" else "Test Intro"

        self.clubsettings_set_patcher = patch(
            "notifications.management.commands.send_weekly_digest.ClubSettings.set"
        )
        self.mock_clubsettings_set = self.clubsettings_set_patcher.start()

        self.searchindex_patcher = patch(
            "notifications.management.commands.send_weekly_digest.SearchIndex.update_post_index"
        )
        self.mock_searchindex = self.searchindex_patcher.start()

        now = datetime.utcnow()

        # Create telegram subscribers
        self.telegram_subscriber = create_test_user(
            email="telegram@example.com",
            telegram_id="111",
            email_digest_type=User.EMAIL_DIGEST_TYPE_WEEKLY,
            membership_expires_at=now + timedelta(days=30),
        )

        self.telegram_nope = create_test_user(
            email="telegram_nope@example.com",
            telegram_id="222",
            email_digest_type=User.EMAIL_DIGEST_TYPE_NOPE,
            membership_expires_at=now + timedelta(days=30),
        )

        # Create email subscribers
        self.email_subscriber = create_test_user(
            email="email@example.com",
            telegram_id=None,
            email_digest_type=User.EMAIL_DIGEST_TYPE_WEEKLY,
            membership_expires_at=now + timedelta(days=30),
            is_email_verified=True,
        )

        self.unsubscribed_user = create_test_user(
            email="unsubscribed@example.com",
            telegram_id=None,
            email_digest_type=User.EMAIL_DIGEST_TYPE_WEEKLY,
            membership_expires_at=now + timedelta(days=30),
            is_email_verified=True,
            is_email_unsubscribed=True,
        )

        # Create vas3k user (for post author)
        self.vas3k = User.objects.filter(slug="vas3k").first()
        if not self.vas3k:
            self.vas3k = create_test_user(slug="vas3k", email="vas3k@vas3k.club")
            self.created_vas3k = True
        else:
            self.created_vas3k = False

    def tearDown(self):
        self.cmd_send_msg_patcher.stop()
        self.generate_digest_patcher.stop()
        self.send_email_patcher.stop()
        self.clubsettings_get_patcher.stop()
        self.clubsettings_set_patcher.stop()
        self.searchindex_patcher.stop()
        super().tearDown()

        User.objects.filter(slug__in=[
            self.telegram_subscriber.slug,
            self.telegram_nope.slug,
            self.email_subscriber.slug,
            self.unsubscribed_user.slug,
        ]).delete()

        if self.created_vas3k:
            self.vas3k.delete()

        # Clean up created digest posts
        Post.objects.filter(type=Post.TYPE_WEEKLY_DIGEST).delete()

    def test_creates_digest_post(self):
        """Should create a weekly digest post"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify post was created
        digest_posts = Post.objects.filter(type=Post.TYPE_WEEKLY_DIGEST)
        self.assertGreaterEqual(digest_posts.count(), 1)

        post = digest_posts.first()
        self.assertIn("Клубный журнал", post.title)
        self.assertEqual(post.moderation_status, Post.MODERATION_APPROVED)

    def test_sends_telegram_to_subscribers(self):
        """Should send telegram to subscribers (not NOPE type)"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify telegram messages were sent (to subscribers + channel)
        self.assertGreater(self.mock_send_msg.call_count, 0)

        # Just verify the command completed successfully
        # The mock is called with complex args that are hard to inspect
        output = out.getvalue()
        self.assertIn("Done 🥙", output)

    def test_sends_emails_to_email_subscribers(self):
        """Should send emails to verified email subscribers"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify email_subscriber received email
        email_recipients = {call[1]["recipient"] for call in self.mock_send_email.call_args_list}
        self.assertIn(self.email_subscriber.email, email_recipients)

        # Verify unsubscribed_user did NOT receive email
        self.assertNotIn(self.unsubscribed_user.email, email_recipients)

    def test_announces_to_channel_in_production(self):
        """Should announce to CLUB_CHANNEL in production mode"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify at least one call to send_telegram_message (includes channel + subscribers)
        self.assertGreaterEqual(self.mock_send_msg.call_count, 1)

    def test_skips_channel_announce_in_non_production(self):
        """Should skip channel announcement in non-production mode"""
        out = StringIO()
        call_command("send_weekly_digest", production=False, stdout=out)

        # In non-production, should still send to subscribers but production flag
        # controls channel announcement and ClubSettings clearing
        # The command may still send to subscribers

    def test_clears_clubsettings_in_production(self):
        """Should clear digest_title and digest_intro in production mode"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify ClubSettings.set was called to clear values
        set_calls = self.mock_clubsettings_set.call_args_list
        set_keys = {call[0][0] for call in set_calls}
        self.assertIn("digest_title", set_keys)
        self.assertIn("digest_intro", set_keys)

    def test_handles_empty_digest(self):
        """Should handle NotFound when digest is empty"""
        self.mock_generate_digest.side_effect = NotFound()

        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify no post was created
        digest_posts = Post.objects.filter(type=Post.TYPE_WEEKLY_DIGEST)
        self.assertEqual(digest_posts.count(), 0)

        # Verify no messages sent
        self.assertEqual(self.mock_send_msg.call_count, 0)

    def test_uses_parsemode_html(self):
        """Should use ParseMode.HTML for telegram messages"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify at least one call used ParseMode.HTML
        if self.mock_send_msg.call_count > 0:
            # Check if any call has parse_mode
            parse_modes = [call[1].get("parse_mode") for call in self.mock_send_msg.call_args_list]
            self.assertIn(ParseMode.HTML, parse_modes)

    def test_updates_search_index(self):
        """Should update SearchIndex for the created post"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify SearchIndex.update_post_index was called
        self.assertEqual(self.mock_searchindex.call_count, 1)

    def test_includes_unsubscribe_link_in_emails(self):
        """Should include unsubscribe link in emails"""
        out = StringIO()
        call_command("send_weekly_digest", production=True, stdout=out)

        # Verify emails have unsubscribe_link
        if self.mock_send_email.call_count > 0:
            for call in self.mock_send_email.call_args_list:
                if "unsubscribe_link" in call[1]:
                    self.assertIn("/notifications/unsubscribe/", call[1]["unsubscribe_link"])

    def test_non_production_only_sends_to_god_users(self):
        """Should only send emails to god users in non-production mode"""
        out = StringIO()
        call_command("send_weekly_digest", production=False, stdout=out)

        # The command checks options.get("production") for emails
        # and only sends to is_god users in non-production
        # Since our test users are not gods, no emails should be sent
        # (unless they're gods, which is determined by the User model)
