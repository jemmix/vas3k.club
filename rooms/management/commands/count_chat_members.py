import logging

from asgiref.sync import async_to_sync
from django.core.management import BaseCommand
from telegram.error import TelegramError

from rooms.models import Room
from notifications.telegram.bot import bot

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Count members in every telegram chat and save to database"

    def handle(self, *args, **options):
        async_to_sync(self._handle_async)(*args, **options)

    async def _handle_async(self, *args, **options):
        async for room in Room.objects.filter(chat_id__isnull=False):
            try:
                member_count = await bot.get_chat_member_count(room.chat_id)

                # Store the count in the database
                room.chat_member_count = member_count
                await room.asave()

                log.info(f"Updated member count for chat {room.slug}: {member_count} members")

            except TelegramError as ex:
                log.warning(f"Failed to get member count for chat {room.slug}: {ex}")

        self.stdout.write("Done 🥙")
