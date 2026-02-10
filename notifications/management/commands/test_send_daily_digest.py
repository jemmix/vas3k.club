"""Tests for notifications/management/commands/send_daily_digest.py command."""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from bot.test_helpers import create_test_user
from club.exceptions import NotFound
from notifications.telegram.tests import BaseNotificationTest
from users.models.user import User


class SendDailyDigestCommandTest(BaseNotificationTest, TestCase):
    """Test the send_daily_digest management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Patch functions in the command module
        self.cmd_send_msg_patcher = patch(
            "notifications.management.commands.send_daily_digest.send_telegram_message"
        )
        self.mock_send_msg = self.cmd_send_msg_patcher.start()

        self.generate_digest_patcher = patch(
            "notifications.management.commands.send_daily_digest.generate_daily_digest"
        )
        self.mock_generate_digest = self.generate_digest_patcher.start()
        self.mock_generate_digest.return_value = "Test digest content"

        now = datetime.utcnow()

        # Create admin user for non-production mode (use WEEKLY to avoid production query)
        admin_email = list(dict(settings.ADMINS).values())[0]
        self.admin_user = create_test_user(
            email=admin_email,
            telegram_id="999",
            email_digest_type=User.EMAIL_DIGEST_TYPE_WEEKLY,  # Not DAILY so production mode won't send to them
            membership_expires_at=now + timedelta(days=30),
        )

        # Create daily subscriber with telegram
        self.daily_subscriber = create_test_user(
            email="daily@example.com",
            telegram_id="111",
            email_digest_type=User.EMAIL_DIGEST_TYPE_DAILY,
            membership_expires_at=now + timedelta(days=30),
        )

        # Create user without telegram_id
        self.no_telegram_user = create_test_user(
            email="notelegram@example.com",
            telegram_id=None,
            email_digest_type=User.EMAIL_DIGEST_TYPE_DAILY,
            membership_expires_at=now + timedelta(days=30),
        )

        # Create user with expired membership
        self.expired_user = create_test_user(
            email="expired@example.com",
            telegram_id="222",
            email_digest_type=User.EMAIL_DIGEST_TYPE_DAILY,
            membership_expires_at=now - timedelta(days=1),
        )

        # Create user with weekly digest type
        self.weekly_user = create_test_user(
            email="weekly@example.com",
            telegram_id="333",
            email_digest_type=User.EMAIL_DIGEST_TYPE_WEEKLY,
            membership_expires_at=now + timedelta(days=30),
        )

    def tearDown(self):
        self.cmd_send_msg_patcher.stop()
        self.generate_digest_patcher.stop()
        super().tearDown()
        User.objects.filter(slug__in=[
            self.admin_user.slug,
            self.daily_subscriber.slug,
            self.no_telegram_user.slug,
            self.expired_user.slug,
            self.weekly_user.slug,
        ]).delete()

    def test_sends_to_daily_subscribers_in_production(self):
        """Should send to daily subscribers with active membership in production mode"""
        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify send_telegram_message was called for daily_subscriber
        self.assertEqual(self.mock_send_msg.call_count, 1)
        call_args = self.mock_send_msg.call_args[1]
        self.assertEqual(call_args["chat"].id, self.daily_subscriber.telegram_id)
        self.assertEqual(call_args["text"], "Test digest content")

        # Verify output
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn(f"Generating digest for user: {self.daily_subscriber.slug}", output)

    def test_sends_only_to_admins_in_non_production(self):
        """Should send only to admin users in non-production mode"""
        out = StringIO()
        call_command("send_daily_digest", production=False, stdout=out)

        # Verify send_telegram_message was called only for admin
        self.assertEqual(self.mock_send_msg.call_count, 1)
        call_args = self.mock_send_msg.call_args[1]
        self.assertEqual(call_args["chat"].id, self.admin_user.telegram_id)

    def test_skips_users_without_telegram_id(self):
        """Should skip users without telegram_id"""
        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify no_telegram_user was not sent to
        telegram_ids = {call[1]["chat"].id for call in self.mock_send_msg.call_args_list}
        self.assertNotIn(None, telegram_ids)

        # Verify output mentions skipping
        output = out.getvalue()
        self.assertIn("User does not have telegram ID", output)

    def test_skips_users_with_empty_digest(self):
        """Should skip users when generate_daily_digest raises NotFound"""
        # Make generate_daily_digest raise NotFound
        self.mock_generate_digest.side_effect = NotFound()

        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify no messages were sent
        self.assertEqual(self.mock_send_msg.call_count, 0)

        # Verify output mentions empty digest
        output = out.getvalue()
        self.assertIn("Empty digest. Skipping", output)

    def test_handles_send_error_and_continues(self):
        """Should handle send errors and continue to next user"""
        # Make send_telegram_message raise exception on first call
        self.mock_send_msg.side_effect = [
            Exception("Send error"),
            None,  # Second call succeeds (if there's a second user)
        ]

        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify command completed
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn("failed", output)

    def test_filters_by_email_digest_type(self):
        """Should only include users with EMAIL_DIGEST_TYPE_DAILY"""
        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify weekly_user was not notified
        telegram_ids = {call[1]["chat"].id for call in self.mock_send_msg.call_args_list}
        self.assertNotIn(self.weekly_user.telegram_id, telegram_ids)

    def test_filters_by_active_membership(self):
        """Should only include users with active membership"""
        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify expired_user was not notified
        telegram_ids = {call[1]["chat"].id for call in self.mock_send_msg.call_args_list}
        self.assertNotIn(self.expired_user.telegram_id, telegram_ids)

    def test_calls_generate_daily_digest_with_user(self):
        """Should call generate_daily_digest with correct user"""
        out = StringIO()
        call_command("send_daily_digest", production=True, stdout=out)

        # Verify generate_daily_digest was called
        self.assertGreaterEqual(self.mock_generate_digest.call_count, 1)

        # Verify it was called with the daily_subscriber
        called_users = {call[0][0].id for call in self.mock_generate_digest.call_args_list}
        self.assertIn(self.daily_subscriber.id, called_users)
