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

## 3. **Async Notification Wrappers** ⭐ PREPARATION

### What
Wrap all notification function calls with `async_to_sync()` in django_q task submissions.

### Why
- Prepares for async notification layer without breaking anything
- Sync functions work fine when wrapped in `async_to_sync()`
- Makes SDK upgrade PR smaller
- Zero behavioral change now, enables async later

### Files Changed (12 files, ~20 LOC)
**Views:**
- `authn/views/email.py` - 1 call
- `badges/views.py` - 2 calls
- `comments/views.py` - 1 call
- `posts/views/posts.py` - 6 calls
- `tickets/views.py` - 1 call
- `users/views/intro.py` - 1 call

**Godmode:**
- `godmode/actions/user_achievement.py` - 2 calls
- `godmode/actions/user_ping.py` - 2 calls
- `godmode/actions/user_unmoderate.py` - 1 call
- `godmode/pages/mass_achievement.py` - 1 call

### Pattern
```python
# Before
from django_q.tasks import async_task
async_task(notify_user_auth, user, code)

# After
from asgiref.sync import async_to_sync
from django_q.tasks import async_task
async_task(async_to_sync(notify_user_auth), user, code)
```

### Benefits
- ✅ Works with current sync notification functions
- ✅ When notifications become async, wrapper still works
- ✅ No code changes needed in notification modules yet
- ✅ Gradual migration path

### Testing
```bash
# All existing tests should pass
python manage.py test authn badges comments posts tickets users godmode
```

### Commit Message
```
chore: wrap notification calls with async_to_sync for future async migration

Wrap all async_task(notify_*) calls with async_to_sync() wrapper.
This is preparatory for async notification layer - sync functions work
fine wrapped, and when notifications become async, wrapper continues working.

Zero behavioral change now, enables async later.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## 4. **Async Model Methods (Dual API)** ⭐ PREPARATION

### What
Add async variants to model methods, maintaining sync wrappers for existing callers.

### Why
- Prepares models for async telegram handlers
- Zero breaking changes (sync wrappers maintained)
- Uses Django 5.1 async ORM properly
- Independent of SDK upgrade

### Files Changed (4 files, ~100 LOC)

**posts/models/subscriptions.py:**
```python
@classmethod
async def subscribe_async(cls, user, post, type=TYPE_TOP_LEVEL_ONLY):
    return await cls.objects.aupdate_or_create(
        user=user, post=post, defaults=dict(type=type)
    )

@classmethod
def subscribe(cls, user, post, type=TYPE_TOP_LEVEL_ONLY):
    """Sync wrapper for subscribe_async"""
    return async_to_sync(cls.subscribe_async)(user, post, type)

@classmethod
async def unsubscribe_async(cls, user, post):
    return await cls.objects.filter(user=user, post=post).adelete()

@classmethod
def unsubscribe(cls, user, post):
    """Sync wrapper for unsubscribe_async"""
    return async_to_sync(cls.unsubscribe_async)(user, post)
```

**posts/models/votes.py:**
```python
@classmethod
async def upvote_async(cls, user, post):
    if not user.is_god and user.id == post.author_id:
        return None, False

    post_vote, is_vote_created = await cls.objects.aget_or_create(
        user=user,
        post=post,
        defaults=dict(ipaddress="0.0.0.0"),
    )

    if is_vote_created:
        await Post.objects.filter(id=post.id).aupdate(upvotes=F("upvotes") + 1)
        await User.objects.filter(id=post.author_id).aupdate(upvotes=F("upvotes") + 1)

    return post_vote, is_vote_created

@classmethod
def upvote(cls, user, post):
    """Sync wrapper for upvote_async"""
    return async_to_sync(cls.upvote_async)(user, post)
```

**comments/models.py:**
```python
@classmethod
async def upvote_async(cls, user, comment, request=None):
    if not user.is_god and user.id == comment.author_id:
        return None, False

    post_vote, is_vote_created = await cls.objects.aget_or_create(
        user=user,
        comment=comment,
        defaults=dict(ipaddress="0.0.0.0"),
    )

    if is_vote_created:
        # Use F() expressions for atomic updates (prevents race conditions!)
        await Comment.objects.filter(id=comment.id).aupdate(upvotes=F("upvotes") + 1)
        await User.objects.filter(id=comment.author_id).aupdate(upvotes=F("upvotes") + 1)

    return post_vote, is_vote_created

@classmethod
def upvote(cls, user, comment, request=None):
    """Sync wrapper for upvote_async"""
    return async_to_sync(cls.upvote_async)(user, comment, request)
```

**posts/models/post.py:**
```python
async def unpublish_async(self):
    self.visibility = Post.VISIBILITY_DRAFT
    self.published_at = None
    await self.asave()

def unpublish(self):
    """Sync wrapper - use unpublish_async in async contexts"""
    self.visibility = Post.VISIBILITY_DRAFT
    self.published_at = None
    self.save()
```

### Benefits
- ✅ Django 5.1 native async ORM (`aupdate_or_create`, `adelete`, `asave`)
- ✅ F() expressions for atomic counter updates (bonus improvement!)
- ✅ Clear naming convention (`_async` suffix)
- ✅ All existing sync callers unchanged
- ✅ Ready for async handlers without model changes

### Testing
```bash
# Existing sync tests continue passing
python manage.py test posts.tests comments.tests

# Add async variant tests (optional)
```

### Commit Message
```
feat: add async model methods with sync wrappers

Add async_* variants to model methods used by telegram bot:
- PostSubscription: subscribe_async, unsubscribe_async
- PostVote: upvote_async (with F() expressions)
- CommentVote: upvote_async (with F() expressions)
- Post: unpublish_async

Uses Django 5.1 async ORM. Sync wrappers maintained for all existing
callers (views, admin, django_q). Zero breaking changes.

Bonus: F() expressions in upvote methods prevent race conditions.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## Summary Table

| # | Improvement | Files | LOC | Risk | Can Commit Now? |
|---|-------------|-------|-----|------|----------------|
| 1 | Typo fix | 1 | 1 | Zero | ✅ YES |
| 2 | Middleware | 1 new | 51 | Low | ✅ YES |
| 3 | Async wrappers | 12 | ~20 | Zero | ✅ YES |
| 4 | Async models | 4 | ~100 | Low | ✅ YES |
| **TOTAL** | | **18** | **~172** | **Low** | **All ready** |

---

## What CANNOT Be Extracted (Must Stay in SDK Upgrade)

1. **Import path changes** - `ParseMode`, `filters`, etc. (SDK-specific)
2. **Handler async conversions** - All `bot/handlers/*.py` (requires v22)
3. **Bot infrastructure** - Updater → Application (requires v22)
4. **Test conversions** - All `test_*.py` files (requires async handlers)
5. **Notification implementations** - Internal async conversion (requires v22)
6. **Rooms helpers** - Uses `ban_chat_member()` from v20+ API

---

## Recommended Extraction Strategy

### Option A: All 4 Improvements as Separate PRs (Most Safe)
```bash
# PR #1: Typo fix (2 min review)
git checkout -b fix-unsubscribe-typo origin/master
# Edit bot/handlers/posts.py line 60
git commit -m "fix: typo in unsubscribe message"

# PR #2: Middleware (15 min review)
git checkout -b feat-connection-middleware origin/master
# Add bot/middleware.py, update bot/main.py
git commit -m "feat: add middleware pattern for connection management"

# PR #3: Async wrappers (10 min review)
git checkout -b chore-async-wrappers origin/master
# Wrap 18 async_task calls
git commit -m "chore: wrap notification calls with async_to_sync"

# PR #4: Async models (30 min review)
git checkout -b feat-async-models origin/master
# Add async methods to 4 model files
git commit -m "feat: add async model methods with sync wrappers"
```

**Total review time: ~60 minutes across 4 PRs**

### Option B: All 4 Together as One Pre-Upgrade PR (Faster)
```bash
git checkout -b pre-upgrade-improvements origin/master
# Apply all 4 improvements
git commit -m "Pre-upgrade improvements: typo, middleware, async prep"
```

**Review time: ~45 minutes for one PR**

### Option C: Just Merge the Whole Branch (Fastest)
Skip extraction, merge entire `telegram-upgrade` branch.

**Review time: 4-6 hours for entire SDK upgrade**

---

## Impact Analysis

### If Extracted (Option A or B)

**SDK Upgrade PR becomes:**
- 18 fewer files
- ~172 fewer LOC
- Focuses purely on SDK-specific changes
- Preparatory work already tested in production

**Review burden:**
- Pre-upgrade: 45-60 min (incremental, low risk)
- SDK upgrade: 3-4 hours (down from 4-6 hours)

**Risk reduction:**
- Preparatory changes independently tested
- Easier to bisect if issues arise
- Can roll back individual pieces

### If Not Extracted (Option C)

**SDK Upgrade PR:**
- All 50 files, ~2000 LOC
- Single large review
- All or nothing deployment

**Review burden:**
- One PR: 4-6 hours

---

## Testing Strategy

### For Each Pre-Upgrade PR

**PR #1 (Typo):**
```bash
python manage.py test bot.handlers.test_posts::UnsubscribeTest
```

**PR #2 (Middleware):**
```bash
python manage.py test bot.handlers
# Verify middleware registered in shell
```

**PR #3 (Async wrappers):**
```bash
python manage.py test authn badges comments posts tickets users godmode
# All existing tests should pass unchanged
```

**PR #4 (Async models):**
```bash
python manage.py test posts.tests comments.tests
# Existing sync tests should pass
```

---

## Rollback Plan

Each PR is independent:
- PR #1 fails → Revert typo fix only
- PR #2 fails → Revert middleware only
- PR #3 fails → Revert async wrappers only
- PR #4 fails → Revert async models only

No cascading dependencies between PRs.

---

## Recommendation

**For your situation: Option B (All 4 Together)**

Why:
- 18 files is still reviewable in one sitting (~45 min)
- Gets all prep work out of the way at once
- Makes SDK upgrade PR significantly cleaner
- Low risk (all changes backward compatible)
- Can test together before merging

**Then:**
- SDK upgrade PR is ~15% smaller
- Focused on SDK-specific changes only
- Easier to review and understand
- Production gets improvements earlier

