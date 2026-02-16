# Улучшения перед апгрейдом telegram SDK

Предлагаю выделить из ветки [`telegram-upgrade`](https://github.com/vas3k/vas3k.club/tree/telegram-upgrade) и смержить в master до основного апгрейда:

## Баги
- Опечатка "от о комментариев" → "от комментариев" в [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L60)
- Некорректная проверка `delete()` в unsubscribe (всегда True) → [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L47-L60)

## Архитектура
- Middleware для `close_old_connections` через Django signals (handler groups -1/1000) → [`bot/middleware.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/middleware.py)

## Async-подготовка
- Обёртки `async_to_sync()` для `async_task(notify_*)` в 12 файлах (views, godmode)
- Async-варианты методов моделей (`subscribe_async`, `upvote_async` и т.д.) с sync-обёртками → [4 файла](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/models/)

**Итого:** 19 файлов, ~178 LOC, все backward compatible

[Детали →](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/PRE_UPGRADE_IMPROVEMENTS.md)
