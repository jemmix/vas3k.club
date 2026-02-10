"""Tests for payments/management/commands/send_subscription_expired.py command."""

from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from bot.test_helpers import create_test_user
from notifications.telegram.tests import BaseNotificationTest
from payments.management.commands.send_subscription_expired import EXPIRATION_DAY
from users.models.user import User


# Use datetime to match what Django will compare against
EXPIRATION_DATETIME = datetime.combine(EXPIRATION_DAY, datetime.min.time()).replace(tzinfo=timezone.utc)


class SendSubscriptionExpiredCommandTest(BaseNotificationTest, TestCase):
    """Test the send_subscription_expired management command"""

    tags = {"telegram", "telegram_notifications"}

    def setUp(self):
        super().setUp()

        # Patch send_telegram_message in the command module (where it's used)
        self.cmd_send_msg_patcher = patch(
            "payments.management.commands.send_subscription_expired.send_telegram_message"
        )
        self.mock_send_msg = self.cmd_send_msg_patcher.start()

        # User expiring in 14 days (should receive notification)
        self.expiring_user = create_test_user(
            email="expiring@example.com",
            telegram_id="111",
            membership_expires_at=EXPIRATION_DATETIME,
            membership_platform_type=User.MEMBERSHIP_PLATFORM_DIRECT,
        )

        # User with recurrent subscription (should be skipped)
        self.recurrent_user = create_test_user(
            email="recurrent@example.com",
            telegram_id="222",
            membership_expires_at=EXPIRATION_DATETIME,
            membership_platform_type=User.MEMBERSHIP_PLATFORM_DIRECT,
            membership_platform_data={"recurrent": True},
        )

        # User without telegram_id (should skip telegram message)
        self.no_telegram_user = create_test_user(
            email="notelegram@example.com",
            telegram_id=None,
            membership_expires_at=EXPIRATION_DATETIME,
            membership_platform_type=User.MEMBERSHIP_PLATFORM_DIRECT,
        )

        # User expiring in 15 days (should not match)
        self.future_user = create_test_user(
            email="future@example.com",
            telegram_id="333",
            membership_expires_at=EXPIRATION_DATETIME + timedelta(days=1),
            membership_platform_type=User.MEMBERSHIP_PLATFORM_DIRECT,
        )

        # Patreon user (should be excluded in production mode)
        self.patreon_user = create_test_user(
            email="patreon@example.com",
            telegram_id="444",
            membership_expires_at=EXPIRATION_DATETIME,
            membership_platform_type=User.MEMBERSHIP_PLATFORM_PATREON,
        )

    def tearDown(self):
        self.cmd_send_msg_patcher.stop()
        super().tearDown()
        User.objects.filter(
            slug__in=[
                self.expiring_user.slug,
                self.recurrent_user.slug,
                self.no_telegram_user.slug,
                self.future_user.slug,
                self.patreon_user.slug,
            ]
        ).delete()

    @patch("payments.management.commands.send_subscription_expired.send_transactional_email")
    def test_sends_notifications_in_production_mode(self, mock_send_email):
        """Should send to non-recurrent users expiring in 14 days, excluding Patreon"""
        out = StringIO()
        call_command("send_subscription_expired", production=True, stdout=out)

        # Verify telegram message sent to expiring_user only
        self.assertEqual(self.mock_send_msg.call_count, 1)
        call_args = self.mock_send_msg.call_args[1]
        self.assertEqual(call_args["chat"].id, self.expiring_user.telegram_id)
        self.assertIn("подписка скоро истечет", str(call_args["text"]))  # Check rendered template content

        # Verify email sent to both expiring_user and no_telegram_user
        self.assertEqual(mock_send_email.call_count, 2)
        recipients = {call[1]["recipient"] for call in mock_send_email.call_args_list}
        self.assertEqual(recipients, {self.expiring_user.email, self.no_telegram_user.email})

        # Verify output
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn("has recurrent subscription, skipping", output)

    @patch("payments.management.commands.send_subscription_expired.EXPIRATION_DAY", EXPIRATION_DAY)
    @patch("payments.management.commands.send_subscription_expired.send_transactional_email")
    def test_sends_to_admins_in_non_production_mode(self, mock_send_email):
        """Should send only to admin users with telegram_id in non-production mode"""
        # Create admin user
        admin_email = list(dict(settings.ADMINS).values())[0]
        admin_user = create_test_user(
            email=admin_email,
            telegram_id="999",
        )

        out = StringIO()
        call_command("send_subscription_expired", production=False, stdout=out)

        # Verify telegram message sent only to admin
        self.assertEqual(self.mock_send_msg.call_count, 1)
        call_args = self.mock_send_msg.call_args[1]
        self.assertEqual(call_args["chat"].id, admin_user.telegram_id)

        # Verify email sent only to admin
        self.assertEqual(mock_send_email.call_count, 1)
        self.assertEqual(mock_send_email.call_args[1]["recipient"], admin_user.email)

        admin_user.delete()

    @patch("payments.management.commands.send_subscription_expired.EXPIRATION_DAY", EXPIRATION_DAY)
    @patch("payments.management.commands.send_subscription_expired.send_transactional_email")
    def test_skips_recurrent_subscribers(self, mock_send_email):
        """Should skip users with recurrent subscriptions"""
        out = StringIO()
        call_command("send_subscription_expired", production=True, stdout=out)

        # Verify recurrent_user did not receive telegram message
        telegram_recipients = {call[1]["chat"].id for call in self.mock_send_msg.call_args_list}
        self.assertNotIn(self.recurrent_user.telegram_id, telegram_recipients)

        # Verify recurrent_user did not receive email
        email_recipients = {call[1]["recipient"] for call in mock_send_email.call_args_list}
        self.assertNotIn(self.recurrent_user.email, email_recipients)

        # Verify output mentions skipping
        output = out.getvalue()
        self.assertIn(f"User {self.recurrent_user.email} has recurrent subscription, skipping", output)

    @patch("payments.management.commands.send_subscription_expired.EXPIRATION_DAY", EXPIRATION_DAY)
    @patch("payments.management.commands.send_subscription_expired.send_transactional_email")
    def test_skips_telegram_for_users_without_telegram_id(self, mock_send_email):
        """Should skip telegram message for users without telegram_id but still send email"""
        out = StringIO()
        call_command("send_subscription_expired", production=True, stdout=out)

        # Verify no_telegram_user did not receive telegram message
        telegram_recipients = {call[1]["chat"].id for call in self.mock_send_msg.call_args_list}
        self.assertNotIn(None, telegram_recipients)

        # Verify no_telegram_user DID receive email
        email_recipients = {call[1]["recipient"] for call in mock_send_email.call_args_list}
        self.assertIn(self.no_telegram_user.email, email_recipients)

    @patch("payments.management.commands.send_subscription_expired.EXPIRATION_DAY", EXPIRATION_DAY)
    @patch("payments.management.commands.send_subscription_expired.send_transactional_email")
    def test_handles_telegram_error(self, mock_send_email):
        """Should handle telegram send errors and continue"""
        # Make send_telegram_message raise an exception
        self.mock_send_msg.side_effect = Exception("Telegram API error")

        out = StringIO()
        call_command("send_subscription_expired", production=True, stdout=out)

        # Verify command completed despite error
        output = out.getvalue()
        self.assertIn("Done 🥙", output)
        self.assertIn("failed", output)

        # Verify email still sent
        self.assertGreater(mock_send_email.call_count, 0)
