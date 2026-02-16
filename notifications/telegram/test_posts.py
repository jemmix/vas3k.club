from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, call, PropertyMock

import telegram
from asgiref.sync import sync_to_async
from django.test import TestCase
from django.template import TemplateDoesNotExist

from notifications.telegram.common import Chat, ADMIN_CHAT, CLUB_CHANNEL, CLUB_CHAT, CLUB_ONLINE, VIBES_CHAT
from notifications.telegram.posts import (
    send_published_post_to_moderators,
    send_intro_changes_to_moderators,
    announce_in_online_channel,
    announce_in_club_channel,
    announce_in_club_chats,
    notify_post_approved,
    notify_post_rejected,
    notify_post_collectible_tag_owners,
    notify_author_friends,
    notify_post_room_subscribers,
    post_reply_markup,
    notify_post_label_changed,
    notify_admins_on_post_label_changed,
    notify_post_coauthors_changed,
    notify_users_by_username,
)
from posts.models.post import Post
from rooms.models import Room, RoomSubscription
from tags.models import Tag, UserTag
from users.models.friends import Friend
from users.models.user import User


class PostNotificationTestBase(TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.user = User.objects.create(
            full_name="Test Author",
            email="author@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        self.user_with_telegram = User.objects.create(
            full_name="Telegram Author",
            email="tgauthor@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="111222",
        )
        self.post = Post.objects.create(
            author=self.user_with_telegram,
            title="Test Post Title",
            text="Some test text for the post.",
            type=Post.TYPE_POST,
        )

    def tearDown(self):
        Post.objects.filter(author__in=[self.user, self.user_with_telegram]).delete()
        self.user.delete()
        self.user_with_telegram.delete()


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class SendPublishedPostToModeratorsTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_admin_chat_with_reply_markup(self, mock_render, mock_send):
        await send_published_post_to_moderators(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        self.assertEqual(kwargs["text"], "rendered_template")
        self.assertIsInstance(kwargs["reply_markup"], telegram.InlineKeyboardMarkup)

    async def test_reply_markup_contains_approve_reject_forgive_buttons(self, mock_render, mock_send):
        await send_published_post_to_moderators(self.post)

        kwargs = mock_send.call_args[1]
        markup = kwargs["reply_markup"]
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        callback_data_values = [btn.callback_data for btn in buttons if btn.callback_data]
        self.assertIn(f"approve_post:{self.post.id}", callback_data_values)
        self.assertIn(f"reject_post:{self.post.id}", callback_data_values)
        self.assertIn(f"forgive_post:{self.post.id}", callback_data_values)

    async def test_reply_markup_contains_reason_buttons_for_post_type(self, mock_render, mock_send):
        await send_published_post_to_moderators(self.post)

        kwargs = mock_send.call_args[1]
        markup = kwargs["reply_markup"]
        buttons = [btn for row in markup.inline_keyboard for btn in row]
        callback_data_values = [btn.callback_data for btn in buttons if btn.callback_data]
        self.assertIn(f"reject_post_title:{self.post.id}", callback_data_values)
        self.assertIn(f"reject_post_design:{self.post.id}", callback_data_values)
        self.assertIn(f"reject_post_value:{self.post.id}", callback_data_values)
        self.assertIn(f"reject_post_inside:{self.post.id}", callback_data_values)

    async def test_renders_moderator_new_post_review_template(self, mock_render, mock_send):
        await send_published_post_to_moderators(self.post)

        mock_render.assert_called_once_with("moderator_new_post_review.html", post=self.post)


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class SendIntroChangesToModeratorsTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_for_intro_type(self, mock_render, mock_send):
        self.post.type = Post.TYPE_INTRO
        await self.post.asave()

        await send_intro_changes_to_moderators(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        self.assertEqual(kwargs["text"], "rendered_template")
        mock_render.assert_called_once_with(
            "moderator_updated_intro.html",
            user=self.post.author,
            intro=self.post,
        )

    async def test_skips_non_intro_type(self, mock_render, mock_send):
        await send_intro_changes_to_moderators(self.post)

        mock_send.assert_not_called()
        mock_render.assert_not_called()


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class AnnounceInOnlineChannelTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_club_online(self, mock_render, mock_send):
        await announce_in_online_channel(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], CLUB_ONLINE)
        self.assertEqual(kwargs["text"], "rendered_template")
        self.assertEqual(kwargs["parse_mode"], telegram.constants.ParseMode.HTML)
        self.assertTrue(kwargs["disable_preview"])

    async def test_renders_channel_post_announce_template(self, mock_render, mock_send):
        await announce_in_online_channel(self.post)

        mock_render.assert_called_once_with("channel_post_announce.html", post=self.post)


@patch("notifications.telegram.posts.send_telegram_image_async")
@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class AnnounceInClubChannelTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_text_without_image(self, mock_render, mock_send, mock_send_image):
        await announce_in_club_channel(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], CLUB_CHANNEL)
        self.assertEqual(kwargs["text"], "rendered_template")
        self.assertFalse(kwargs["disable_preview"])
        self.assertEqual(kwargs["parse_mode"], telegram.constants.ParseMode.HTML)
        mock_send_image.assert_not_called()

    async def test_sends_image_when_provided(self, mock_render, mock_send, mock_send_image):
        await announce_in_club_channel(self.post, image="https://example.com/image.jpg")

        mock_send_image.assert_called_once()
        kwargs = mock_send_image.call_args[1]
        self.assertEqual(kwargs["chat"], CLUB_CHANNEL)
        self.assertEqual(kwargs["image_url"], "https://example.com/image.jpg")
        self.assertEqual(kwargs["text"], "rendered_template")
        mock_send.assert_not_called()

    async def test_uses_custom_announce_text_when_provided(self, mock_render, mock_send, mock_send_image):
        await announce_in_club_channel(self.post, announce_text="Custom text")

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["text"], "Custom text")
        mock_render.assert_not_called()


@patch("notifications.telegram.posts.post_reply_markup", return_value=None)
@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class AnnounceInClubChatsTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_club_chat_for_everywhere_visibility(self, mock_render, mock_send, mock_markup):
        self.post.visibility = Post.VISIBILITY_EVERYWHERE
        await self.post.asave()

        await announce_in_club_chats(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], CLUB_CHAT)
        self.assertEqual(kwargs["parse_mode"], telegram.constants.ParseMode.HTML)
        self.assertTrue(kwargs["disable_preview"])

    async def test_sends_to_club_chat_when_no_room(self, mock_render, mock_send, mock_markup):
        self.post.room = None
        await self.post.asave()

        await announce_in_club_chats(self.post)

        called_chats = [c[1]["chat"] for c in mock_send.call_args_list]
        self.assertIn(CLUB_CHAT, called_chats)

    async def test_sends_to_room_chat_when_room_has_chat_id(self, mock_render, mock_send, mock_markup):
        room = await Room.objects.acreate(slug="testroom", title="Test Room", color="#000000", chat_id="room_chat_123")
        self.post.room = room
        self.post.visibility = Post.VISIBILITY_EVERYWHERE
        await self.post.asave()

        await announce_in_club_chats(self.post)

        called_chats = [c[1]["chat"] for c in mock_send.call_args_list]
        self.assertIn(Chat(id="room_chat_123"), called_chats)
        self.assertIn(CLUB_CHAT, called_chats)
        await room.adelete()

    async def test_does_not_send_to_room_chat_when_send_new_posts_disabled(self, mock_render, mock_send, mock_markup):
        room = await Room.objects.acreate(
            slug="quietroom", title="Quiet Room", color="#000000",
            chat_id="quiet_chat_123", send_new_posts_to_chat=False,
        )
        self.post.room = room
        self.post.visibility = Post.VISIBILITY_EVERYWHERE
        await self.post.asave()

        await announce_in_club_chats(self.post)

        called_chats = [c[1]["chat"] for c in mock_send.call_args_list]
        self.assertNotIn(Chat(id="quiet_chat_123"), called_chats)
        await room.adelete()


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyPostApprovedTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_author_with_telegram_id(self, mock_render, mock_send):
        await notify_post_approved(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="111222"))
        self.assertEqual(kwargs["text"], "rendered_template")
        mock_render.assert_called_once_with("post_approved.html", post=self.post)

    async def test_skips_without_telegram_id(self, mock_render, mock_send):
        post = await Post.objects.acreate(
            author=self.user,
            title="No TG Post",
            text="Text",
        )
        result = await notify_post_approved(post)

        mock_send.assert_not_called()
        self.assertIsNone(result)
        await post.adelete()

    async def test_uses_room_template_for_room_only_post(self, mock_render, mock_send):
        room = await Room.objects.acreate(slug="approveroom", title="Approve Room", color="#111111")
        self.post.room = room
        self.post.is_room_only = True
        await self.post.asave()

        await notify_post_approved(self.post)

        mock_render.assert_called_once_with("post_approved_in_room.html", post=self.post)
        await room.adelete()


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyPostRejectedTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_with_reason(self, mock_render, mock_send):
        reason = MagicMock(value="title")
        await notify_post_rejected(self.post, reason)

        mock_render.assert_called_once_with("post_rejected/title.html", post=self.post)
        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="111222"))
        self.assertEqual(kwargs["text"], "rendered_template")

    async def test_falls_back_to_draft_template_on_missing_template(self, mock_render, mock_send):
        mock_render.side_effect = [TemplateDoesNotExist("post_rejected/unknown.html"), "fallback_rendered"]
        reason = MagicMock(value="unknown")

        await notify_post_rejected(self.post, reason)

        self.assertEqual(mock_render.call_count, 2)
        mock_render.assert_any_call("post_rejected/unknown.html", post=self.post)
        mock_render.assert_any_call("post_rejected/draft.html", post=self.post)

    async def test_skips_without_telegram_id(self, mock_render, mock_send):
        post = await Post.objects.acreate(
            author=self.user,
            title="No TG Post",
            text="Text",
        )
        reason = MagicMock(value="title")
        await notify_post_rejected(post, reason)

        mock_send.assert_not_called()
        await post.adelete()


@patch("notifications.telegram.posts.post_reply_markup", return_value=None)
@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyPostCollectibleTagOwnersTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_notifies_tag_owners(self, mock_render, mock_send, mock_markup):
        now = datetime.now(timezone.utc)
        tag_owner = await User.objects.acreate(
            full_name="Tag Owner",
            email="tagowner@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="333444",
        )
        tag = await Tag.objects.acreate(code="testcollect", name="Test Collectible", group=Tag.GROUP_COLLECTIBLE)
        await UserTag.objects.acreate(user=tag_owner, tag=tag, name="test tag")

        self.post.collectible_tag_code = "testcollect"
        await self.post.asave()

        await notify_post_collectible_tag_owners(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="333444"))

        await UserTag.objects.filter(user=tag_owner).adelete()
        await tag.adelete()
        await tag_owner.adelete()

    async def test_skips_without_collectible_tag_code(self, mock_render, mock_send, mock_markup):
        self.post.collectible_tag_code = None
        await self.post.asave()

        await notify_post_collectible_tag_owners(self.post)

        mock_send.assert_not_called()

    async def test_skips_tag_owner_without_telegram_id(self, mock_render, mock_send, mock_markup):
        now = datetime.now(timezone.utc)
        tag_owner_no_tg = await User.objects.acreate(
            full_name="No TG Tag Owner",
            email="notgtagowner@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        tag = await Tag.objects.acreate(code="testcollect2", name="Test Collectible 2", group=Tag.GROUP_COLLECTIBLE)
        await UserTag.objects.acreate(user=tag_owner_no_tg, tag=tag, name="test tag 2")

        self.post.collectible_tag_code = "testcollect2"
        await self.post.asave()

        await notify_post_collectible_tag_owners(self.post)

        mock_send.assert_not_called()

        await UserTag.objects.filter(user=tag_owner_no_tg).adelete()
        await tag.adelete()
        await tag_owner_no_tg.adelete()


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyAuthorFriendsTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_notifies_mentioned_users(self, mock_render, mock_send):
        now = datetime.now(timezone.utc)
        mentioned_user = await User.objects.acreate(
            full_name="Mentioned User",
            slug="mentioneduser",
            email="mentioned@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="555666",
        )
        self.post.text = "Hello @mentioneduser check this out"
        await self.post.asave()

        await notify_author_friends(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="555666"))

        await mentioned_user.adelete()

    async def test_notifies_friends(self, mock_render, mock_send):
        now = datetime.now(timezone.utc)
        friend_user = await User.objects.acreate(
            full_name="Friend User",
            email="friend@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="777888",
        )
        await Friend.objects.acreate(user_from=friend_user, user_to=self.user_with_telegram, is_subscribed_to_posts=True)
        self.post.text = "No mentions here"
        await self.post.asave()

        await notify_author_friends(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="777888"))

        await Friend.objects.filter(user_from=friend_user).adelete()
        await friend_user.adelete()

    async def test_deduplicates_mentioned_user_who_is_also_friend(self, mock_render, mock_send):
        now = datetime.now(timezone.utc)
        dual_user = await User.objects.acreate(
            full_name="Dual User",
            slug="dualuser",
            email="dual@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="999000",
        )
        await Friend.objects.acreate(user_from=dual_user, user_to=self.user_with_telegram, is_subscribed_to_posts=True)
        self.post.text = "Hey @dualuser check this"
        await self.post.asave()

        await notify_author_friends(self.post)

        # Should only be notified once (as mention), not twice
        self.assertEqual(mock_send.call_count, 1)

        await Friend.objects.filter(user_from=dual_user).adelete()
        await dual_user.adelete()

    async def test_skips_friend_not_subscribed_to_posts(self, mock_render, mock_send):
        now = datetime.now(timezone.utc)
        unsub_friend = await User.objects.acreate(
            full_name="Unsub Friend",
            email="unsub@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="111333",
        )
        await Friend.objects.acreate(
            user_from=unsub_friend, user_to=self.user_with_telegram, is_subscribed_to_posts=False,
        )
        self.post.text = "No mentions"
        await self.post.asave()

        await notify_author_friends(self.post)

        mock_send.assert_not_called()

        await Friend.objects.filter(user_from=unsub_friend).adelete()
        await unsub_friend.adelete()


@patch("notifications.telegram.posts.post_reply_markup", return_value=None)
@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyPostRoomSubscribersTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_notifies_subscribers(self, mock_render, mock_send, mock_markup):
        now = datetime.now(timezone.utc)
        subscriber_user = await User.objects.acreate(
            full_name="Subscriber",
            email="subscriber@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="444555",
        )
        room = await Room.objects.acreate(slug="subroom", title="Sub Room", color="#222222")
        await RoomSubscription.objects.acreate(user=subscriber_user, room=room)
        self.post.room = room
        await self.post.asave()

        await notify_post_room_subscribers(self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="444555"))

        await RoomSubscription.objects.filter(user=subscriber_user).adelete()
        await room.adelete()
        await subscriber_user.adelete()

    async def test_skips_without_room(self, mock_render, mock_send, mock_markup):
        self.post.room = None
        await self.post.asave()

        await notify_post_room_subscribers(self.post)

        mock_send.assert_not_called()

    async def test_skips_subscriber_without_telegram_id(self, mock_render, mock_send, mock_markup):
        now = datetime.now(timezone.utc)
        no_tg_subscriber = await User.objects.acreate(
            full_name="No TG Sub",
            email="notgsub@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
        )
        room = await Room.objects.acreate(slug="subroom2", title="Sub Room 2", color="#333333")
        await RoomSubscription.objects.acreate(user=no_tg_subscriber, room=room)
        self.post.room = room
        await self.post.asave()

        await notify_post_room_subscribers(self.post)

        mock_send.assert_not_called()

        await RoomSubscription.objects.filter(user=no_tg_subscriber).adelete()
        await room.adelete()
        await no_tg_subscriber.adelete()


@patch("notifications.telegram.posts.reverse", return_value="/post/test-post/")
@patch("notifications.telegram.posts.settings")
class PostReplyMarkupTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_returns_inline_keyboard_markup(self, mock_settings, mock_reverse):
        mock_settings.APP_HOST = "https://example.com"

        result = post_reply_markup(self.post)

        self.assertIsInstance(result, telegram.InlineKeyboardMarkup)

    async def test_contains_upvote_link_subscribe_buttons(self, mock_settings, mock_reverse):
        mock_settings.APP_HOST = "https://example.com"

        result = post_reply_markup(self.post)

        buttons = [btn for row in result.inline_keyboard for btn in row]
        callback_data_values = [btn.callback_data for btn in buttons if btn.callback_data]
        self.assertIn(f"upvote_post:{self.post.id}", callback_data_values)
        self.assertIn(f"subscribe:{self.post.id}", callback_data_values)

        url_buttons = [btn for btn in buttons if btn.url]
        self.assertEqual(len(url_buttons), 1)
        self.assertEqual(url_buttons[0].url, "https://example.com/post/test-post/")


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyPostLabelChangedTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_label_set_to_admin_chat(self, mock_render, mock_send):
        post = MagicMock()
        post.label_code = "good"
        post.label = {"notify": False}
        post.author.telegram_id = None

        await notify_post_label_changed(post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        mock_render.assert_called_once_with("moderator_label_set.html", post=post)

    async def test_sends_label_removed_to_admin_chat(self, mock_render, mock_send):
        post = MagicMock()
        post.label_code = None

        await notify_post_label_changed(post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], ADMIN_CHAT)
        mock_render.assert_called_once_with("moderator_label_removed.html", post=post)

    async def test_sends_to_author_when_label_has_notify_true(self, mock_render, mock_send):
        post = MagicMock()
        post.label_code = "good"
        post.label = {"notify": True}
        post.author.telegram_id = "111222"

        await notify_post_label_changed(post)

        self.assertEqual(mock_send.call_count, 2)
        # First call to admin
        admin_kwargs = mock_send.call_args_list[0][1]
        self.assertEqual(admin_kwargs["chat"], ADMIN_CHAT)
        # Second call to author
        author_kwargs = mock_send.call_args_list[1][1]
        self.assertEqual(author_kwargs["chat"], Chat(id="111222"))

    async def test_does_not_send_to_author_when_label_notify_false(self, mock_render, mock_send):
        post = MagicMock()
        post.label_code = "meh"
        post.label = {"notify": False}
        post.author.telegram_id = "111222"

        await notify_post_label_changed(post)

        self.assertEqual(mock_send.call_count, 1)

    async def test_does_not_send_to_author_without_telegram_id(self, mock_render, mock_send):
        post = MagicMock()
        post.label_code = "good"
        post.label = {"notify": True}
        post.author.telegram_id = None

        await notify_post_label_changed(post)

        self.assertEqual(mock_send.call_count, 1)


@patch("notifications.telegram.posts.send_telegram_message_async")
class NotifyAdminsOnPostLabelChangedTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_admin_and_vibes_chat(self, mock_send):
        post = MagicMock()
        post.title = "Test Post"
        post.label_code = "good"

        await notify_admins_on_post_label_changed(post)

        self.assertEqual(mock_send.call_count, 2)
        chats_called = [c[1]["chat"] for c in mock_send.call_args_list]
        self.assertIn(ADMIN_CHAT, chats_called)
        self.assertIn(VIBES_CHAT, chats_called)

    async def test_message_contains_post_title_and_label(self, mock_send):
        post = MagicMock()
        post.title = "My Great Post"
        post.label_code = "excellent"

        await notify_admins_on_post_label_changed(post)

        text = mock_send.call_args_list[0][1]["text"]
        self.assertIn("My Great Post", text)
        self.assertIn("excellent", text)


@patch("notifications.telegram.posts.notify_users_by_username")
class NotifyPostCoauthorsChangedTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_notifies_added_and_removed_coauthors(self, mock_notify):
        post = MagicMock()
        post.coauthors = ["alice", "bob"]

        history_current = MagicMock()
        history_current.coauthors = ["alice", "bob"]
        history_old = MagicMock()
        history_old.coauthors = ["alice", "charlie"]

        post.history.all.return_value = [history_current, history_old]

        await notify_post_coauthors_changed(post)

        self.assertEqual(mock_notify.call_count, 2)
        # added = {"bob"}, removed = {"charlie"}
        added_call = mock_notify.call_args_list[0]
        removed_call = mock_notify.call_args_list[1]
        self.assertEqual(added_call[0][0], {"bob"})
        self.assertEqual(added_call[0][1], "coauthor_added.html")
        self.assertEqual(removed_call[0][0], {"charlie"})
        self.assertEqual(removed_call[0][1], "coauthor_removed.html")

    async def test_treats_no_history_as_empty_old_coauthors(self, mock_notify):
        post = MagicMock()
        post.coauthors = ["alice"]

        history_current = MagicMock()
        history_current.coauthors = ["alice"]
        post.history.all.return_value = [history_current]

        await notify_post_coauthors_changed(post)

        added_call = mock_notify.call_args_list[0]
        removed_call = mock_notify.call_args_list[1]
        self.assertEqual(added_call[0][0], {"alice"})
        self.assertEqual(removed_call[0][0], set())


@patch("notifications.telegram.posts.send_telegram_message_async")
@patch("notifications.telegram.posts.render_html_message", return_value="rendered_template")
class NotifyUsersByUsernameTest(PostNotificationTestBase):
    tags = {"telegram", "telegram_notifications"}

    async def test_sends_to_users_by_slug(self, mock_render, mock_send):
        await notify_users_by_username({self.user_with_telegram.slug}, "coauthor_added.html", self.post)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        self.assertEqual(kwargs["chat"], Chat(id="111222"))
        mock_render.assert_called_once_with("coauthor_added.html", post=self.post)

    async def test_skips_user_without_telegram_id(self, mock_render, mock_send):
        await notify_users_by_username({self.user.slug}, "coauthor_added.html", self.post)

        mock_send.assert_not_called()

    async def test_skips_nonexistent_user(self, mock_render, mock_send):
        await notify_users_by_username({"nonexistentuser"}, "coauthor_added.html", self.post)

        mock_send.assert_not_called()

    async def test_sends_to_multiple_users(self, mock_render, mock_send):
        now = datetime.now(timezone.utc)
        another_user = await User.objects.acreate(
            full_name="Another TG User",
            email="anothertg@example.com",
            membership_started_at=now,
            membership_expires_at=now + timedelta(days=30),
            moderation_status=User.MODERATION_STATUS_APPROVED,
            telegram_id="222333",
        )

        await notify_users_by_username(
            {self.user_with_telegram.slug, another_user.slug},
            "coauthor_added.html",
            self.post,
        )

        self.assertEqual(mock_send.call_count, 2)
        await another_user.adelete()
