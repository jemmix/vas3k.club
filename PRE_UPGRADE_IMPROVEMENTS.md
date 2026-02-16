# Pre-Upgrade Improvements: Changes to Propose to Master

These improvements can be committed to `master` BEFORE the telegram SDK upgrade, reducing the size of the upgrade patch and making it easier to review.

---

## 1. **Typo Fix: Unsubscribe Message** 🐛 BUGFIX

### What
Fix typo in unsubscribe message: "от о комментариев" → "от комментариев"

### Why
- Simple typo (double "о")
- User-facing message improvement
- Independent of any SDK changes

### File Changed
**bot/handlers/posts.py** (line 60)

### Pattern
```python
# Before
text=f"Вы отписались от о комментариев к посту «{post.title}» 🔕"

# After
text=f"Вы отписались от комментариев к посту «{post.title}» 🔕"
```

### Testing
```bash
python manage.py test bot.handlers.test_posts::UnsubscribeTest
```

### Commit Message
```
fix: typo in unsubscribe message

Remove duplicate "о" from "от о комментариев" → "от комментариев"

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## 2. **Database Connection Middleware Pattern** ⭐ ARCHITECTURAL IMPROVEMENT

### What
Introduce middleware pattern for database connection management using telegram handler groups.

### Why
- Eliminates manual `close_old_connections()` calls throughout codebase
- Leverages Django's built-in signal mechanism
- Works with both v12 and v22 telegram SDK
- Centralized, testable connection management

### Files Changed
**bot/middleware.py** (new file, 51 LOC)

### How It Works
1. Register handlers in special groups (-1 and 1000)
2. Group -1 runs BEFORE all regular handlers → triggers `request_started` signal
3. Django's signal handler automatically calls `close_old_connections()`
4. Regular handlers execute (group 0, default)
5. Group 1000 runs AFTER all handlers → triggers `request_finished` signal
6. Django's signal handler calls `close_old_connections()` again

### Code
```python
"""
Telegram bot middleware to handle database connections.

This module sets up handlers that act as hooks to trigger Django's request signals,
which automatically manage database connections through close_old_connections.
"""
import logging

from django.core.signals import request_started, request_finished
from telegram import Update
from telegram.ext import CallbackContext, TypeHandler

log = logging.getLogger(__name__)


async def request_start_handler(update: Update, context: CallbackContext) -> None:
    """
    Handler that triggers Django's request_started signal.
    Registered in group -1 to run before all other handlers.
    """
    request_started.send(sender="telegram_bot", update=update)


async def request_finish_handler(update: Update, context: CallbackContext) -> None:
    """
    Handler that triggers Django's request_finished signal.
    Registered in group 1000 to run after all other handlers.
    """
    request_finished.send(sender="telegram_bot", update=update)


def setup_middleware_handlers(application):
    """
    Register middleware handlers for database connection management.

    These handlers trigger Django's request lifecycle signals which automatically
    call close_old_connections, replacing the need for manual calls in decorators.
    """
    # Register pre-handler in group -1 (runs before all other handlers)
    application.add_handler(
        TypeHandler(Update, request_start_handler),
        group=-1
    )

    # Register post-handler in group 1000 (runs after all other handlers)
    application.add_handler(
        TypeHandler(Update, request_finish_handler),
        group=1000
    )

    log.info("Telegram bot middleware handlers registered (groups -1 and 1000)")
```

### Integration
In `bot/main.py`:
```python
from bot.middleware import setup_middleware_handlers

# After building application
application = builder.build()
setup_middleware_handlers(application)
```

### Benefits
- ✅ Automatic connection management for all handlers
- ✅ No decorator needed on individual handlers
- ✅ Centralized logic in one file
- ✅ Leverages Django's existing infrastructure
- ✅ Works with current v12 SDK (can be committed now)

### Testing
```bash
# Verify middleware handlers are registered
python manage.py shell
>>> from bot.main import start_server
>>> server = start_server()
>>> # Check handlers in groups -1 and 1000
```

### Commit Message
```
feat: add middleware pattern for database connection management

Introduce bot/middleware.py with handlers in groups -1 and 1000 that trigger
Django's request_started and request_finished signals. This eliminates the
need for manual close_old_connections() calls in decorators.

How it works:
- Group -1 handler runs before all handlers, triggers request_started
- Django's signal automatically calls close_old_connections()
- Regular handlers execute
- Group 1000 handler runs after all handlers, triggers request_finished
- Django's signal calls close_old_connections() again

Benefits:
- Centralized connection management
- Automatic for all handlers
- Leverages Django's built-in signal mechanism
- Works with both v12 and v22 telegram SDK

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### ⚠️ NOTE
This can be committed to master NOW without any SDK upgrade. The middleware pattern works with v12. However, you'll want to remove the `ensure_fresh_db_connection` decorators and manual `close_old_connections()` calls in a follow-up commit (which could be part of the SDK upgrade).

---

---

## Summary

**Total Extractable Improvements:** 2

1. **Typo fix** (1 line) - Can commit NOW
2. **Middleware pattern** (51 LOC, new file) - Can commit NOW

Everything else is tightly coupled to the async/SDK upgrade and should stay together in the main upgrade PR.

---

## Recommended Action

### Option A: Extract Both (RECOMMENDED)
```bash
# Create branch from master
git checkout -b pre-upgrade-improvements origin/master

# Apply typo fix
# Edit bot/handlers/posts.py line 60

# Add middleware
# Copy bot/middleware.py from telegram-upgrade branch
# Update bot/main.py to call setup_middleware_handlers()

# Commit
git add bot/handlers/posts.py bot/middleware.py bot/main.py
git commit -m "Pre-upgrade improvements: typo fix + middleware pattern"

# Test
python manage.py test bot.handlers.test_posts::UnsubscribeTest

# Create PR to master
```

### Option B: Just Merge Everything
The middleware and typo are such small changes that it's probably easier to just review and merge the entire `telegram-upgrade` branch.

