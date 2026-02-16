# Улучшения, найденные при работе над telegram SDK

В процессе работы над апгрейдом telegram SDK нашёл несколько улучшений, которые имеет смысл применить независимо:

## Баги
- **Опечатка** "от о комментариев" → "от комментариев" в [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L60)
- **Некорректная проверка unsubscribe** — сейчас проверяем tuple вместо count, всегда показываем "успешно отписались" даже если не были подписаны → [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L47-L60)

## Архитектура
- **Middleware для DB connections** — использовать handler groups (-1/1000) для автоматического вызова `close_old_connections()` через Django signals вместо ручных вызовов в декораторах → [`bot/middleware.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/middleware.py)

## Подготовка к async (для будущего апгрейда)
- **Обёртки async_to_sync** — обернуть `async_task(notify_*)` сейчас, чтобы потом не менять все вызовы при миграции на async уведомления (12 файлов: views, godmode)
- **Async-варианты методов** — добавить `subscribe_async()`, `upvote_async()` и т.д. с sync-обёртками для совместимости, используя Django 5.1 async ORM → [4 файла models](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/models/)

**Все изменения backward compatible, ничего не ломают.**

[Детали →](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/PRE_UPGRADE_IMPROVEMENTS.md)
