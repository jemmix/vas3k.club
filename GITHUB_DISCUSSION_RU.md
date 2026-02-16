# Улучшения перед апгрейдом telegram SDK

Предлагаю выделить несколько улучшений из ветки `telegram-upgrade` и смержить их в `master` **до** основного апгрейда SDK. Это уменьшит размер главного PR и позволит исправить баги раньше.

---

## 🐛 Исправления багов (2)

### 1. Опечатка в сообщении об отписке

**Проблема:** "от о комментариев" → "от комментариев"

**Файл:** [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L60)

**Изменение:** 1 строка

---

### 2. Некорректная проверка результата отписки

**Проблема:** Проверяем tuple вместо количества удалённых записей. `if is_unsubscribed:` всегда `True`, даже если пользователь не был подписан.

**Правильно:** `deleted_count, _ = PostSubscription.unsubscribe(...)` и `if deleted_count > 0:`

**Файл:** [`bot/handlers/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/handlers/posts.py#L47-L60)

**Изменение:** 2 строки

---

## ⭐ Архитектурное улучшение (1)

### 3. Middleware для управления соединениями с БД

**Идея:** Использовать handler groups (-1 и 1000) в telegram bot для автоматического вызова `close_old_connections()` через Django signals.

**Как работает:**
- Group -1: вызывает `request_started` → Django автоматически вызывает `close_old_connections()`
- Обычные handlers (group 0)
- Group 1000: вызывает `request_finished` → Django снова вызывает `close_old_connections()`

**Файлы:**
- [`bot/middleware.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/middleware.py) (новый файл, 51 LOC)
- [`bot/main.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/bot/main.py#L88-L91) (интеграция)

**Преимущества:**
- ✅ Убирает ручные вызовы `close_old_connections()` из декораторов
- ✅ Работает с текущей версией v12 (можно коммитить прямо сейчас)
- ✅ Централизованная логика
- ✅ Использует встроенный механизм Django

**Изменение:** 1 новый файл + 4 строки в main.py

---

## 🔧 Подготовка к async (2)

### 4. Обёртки async_to_sync для уведомлений

**Идея:** Обернуть все вызовы `async_task(notify_*)` в `async_to_sync()` для будущей async-миграции.

**Почему сейчас:**
- Sync-функции работают нормально обёрнутыми
- Когда уведомления станут async, обёртка продолжит работать
- Нулевое изменение поведения сейчас, подготовка на будущее

**Файлы (12 шт):**
- [`authn/views/email.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/authn/views/email.py)
- [`badges/views.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/badges/views.py)
- [`comments/views.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/comments/views.py)
- [`posts/views/posts.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/views/posts.py)
- [`tickets/views.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/tickets/views.py)
- [`users/views/intro.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/users/views/intro.py)
- [`godmode/actions/user_achievement.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/godmode/actions/user_achievement.py)
- [`godmode/actions/user_ping.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/godmode/actions/user_ping.py)
- [`godmode/actions/user_unmoderate.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/godmode/actions/user_unmoderate.py)
- [`godmode/pages/mass_achievement.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/godmode/pages/mass_achievement.py)

**Паттерн:**
```python
# Было
async_task(notify_user_auth, user, code)

# Станет
from asgiref.sync import async_to_sync
async_task(async_to_sync(notify_user_auth), user, code)
```

**Изменение:** ~20 LOC в 12 файлах

---

### 5. Async-варианты методов моделей (Dual API)

**Идея:** Добавить `*_async()` методы с sync-обёртками для совместимости.

**Файлы (4 шт):**
- [`posts/models/subscriptions.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/models/subscriptions.py) → `subscribe_async`, `unsubscribe_async`
- [`posts/models/votes.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/models/votes.py) → `upvote_async` + поддержка coauthors
- [`comments/models.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/comments/models.py) → `upvote_async`
- [`posts/models/post.py`](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/posts/models/post.py) → `unpublish_async`

**Паттерн:**
```python
@classmethod
async def subscribe_async(cls, user, post, type=TYPE_TOP_LEVEL_ONLY):
    return await cls.objects.aupdate_or_create(user=user, post=post, defaults=dict(type=type))

@classmethod
def subscribe(cls, user, post, type=TYPE_TOP_LEVEL_ONLY):
    """Sync wrapper for subscribe_async"""
    return async_to_sync(cls.subscribe_async)(user, post, type)
```

**Преимущества:**
- ✅ Django 5.1 async ORM (`aupdate_or_create`, `adelete`, `asave`)
- ✅ Нулевые breaking changes (sync-обёртки сохранены)
- ✅ Готовность к async handlers
- ✅ Бонус: PostVote.upvote_async теперь обновляет счётчики coauthors

**Изменение:** ~100 LOC в 4 файлах

---

## 📊 Итого

| Тип | Кол-во | Строк | Файлов |
|-----|--------|-------|--------|
| Баги | 2 | 3 | 1 |
| Архитектура | 1 | 55 | 2 |
| Async-подготовка | 2 | ~120 | 16 |
| **ВСЕГО** | **5** | **~178** | **19** |

**Эффект:** Уменьшает основной PR апгрейда на ~8% (178 строк из ~2000)

---

## 🎯 Варианты действий

### Вариант А: Поэтапно (рекомендую)

1. **PR #1:** Баги (#1, #2) — 5 мин ревью
2. **PR #2:** Middleware (#3) — 15 мин ревью
3. **PR #3:** Async-подготовка (#4, #5) — 45 мин ревью

**Итого:** 3 PR, ~65 мин ревью

### Вариант Б: Всё вместе

Один PR со всеми 5 улучшениями — 60 мин ревью

### Вариант В: Просто смержить всю ветку

Без выделения, полный SDK апгрейд целиком — 4-6 часов ревью

---

## ✅ Преимущества выделения

**Если выделить (А или Б):**
- ✅ Баги в продакшене раньше на несколько недель
- ✅ Каждое улучшение тестируется независимо
- ✅ Основной PR апгрейда чище и фокусируется только на SDK
- ✅ Легче откатить отдельные куски при проблемах

**Если не выделять (В):**
- Один большой PR (50 файлов, ~2000 LOC)
- Баги ждут полного апгрейда
- Всё или ничего при деплое

---

## 📝 Ссылки

- **Ветка с изменениями:** [`telegram-upgrade`](https://github.com/vas3k/vas3k.club/tree/telegram-upgrade)
- **Полная документация:** [TELEGRAM_UPGRADE_SUMMARY.md](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/TELEGRAM_UPGRADE_SUMMARY.md)
- **Детали улучшений:** [PRE_UPGRADE_IMPROVEMENTS.md](https://github.com/vas3k/vas3k.club/blob/telegram-upgrade/PRE_UPGRADE_IMPROVEMENTS.md)
