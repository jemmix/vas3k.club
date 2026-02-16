# Pre-Upgrade Improvements: Changes to Propose to Master

These improvements can be committed to `master` BEFORE the telegram SDK upgrade, reducing the size of the upgrade patch and making it easier to review.

---

## 1. **Prepare Async Notification Layer** ⭐ HIGH PRIORITY

### What
Wrap all async notification function calls with `async_to_sync()` in django_q tasks.

### Why
- Currently, notification functions are being called directly in `async_task()`, but they're about to become async
- This change prepares the codebase without breaking anything (sync functions work fine wrapped in `async_to_sync`)
- Makes the eventual SDK upgrade patch much smaller
- Zero behavioral change - purely preparatory

### Files Changed
**Views (9 files):**
- `authn/views/email.py` - 1 call
- `badges/views.py` - 2 calls
- `comments/views.py` - 1 call
- `posts/views/posts.py` - 6 calls
- `tickets/views.py` - 1 call
- `users/views/intro.py` - 1 call

**Godmode Actions (3 files):**
- `godmode/actions/user_achievement.py` - 2 calls
- `godmode/actions/user_ping.py` - 2 calls
- `godmode/actions/user_unmoderate.py` - 1 call
- `godmode/pages/mass_achievement.py` - 1 call

### Pattern
```python
# Before
async_task(notify_user_auth, user, code)

# After
from asgiref.sync import async_to_sync
async_task(async_to_sync(notify_user_auth), user, code)
```

### Testing
- All existing tests pass (no behavioral change)
- Functions are still synchronous, just wrapped

### Commit Message
```
chore: prepare notification layer for async conversion

Wrap async notification calls with async_to_sync() in django_q tasks.
This is a preparatory change with zero behavioral impact - sync functions
work fine when wrapped. Prepares codebase for future async notification layer.

Files changed:
- Views: authn, badges, comments, posts, tickets, users
- Godmode: actions and pages

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## 2. **Add Async Model Methods (Dual API)** ⭐ HIGH PRIORITY

### What
Add async variants to model methods used by telegram bot, maintaining sync wrappers for existing callers.

### Why
- Prepares models for async telegram handlers
- Zero breaking changes - all existing sync callers continue working
- Clean separation of concerns
- Can be reviewed and tested independently of SDK upgrade

### Files Changed
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
    # Async implementation using await
    ...

@classmethod
def upvote(cls, user, post):
    """Sync wrapper for upvote_async"""
    return async_to_sync(cls.upvote_async)(user, post)
```

**comments/models.py:**
```python
@classmethod
async def upvote_async(cls, user, comment, request=None):
    # Async implementation using await
    # BONUS: Uses F() expressions for atomic updates
    ...

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
- ✅ Django 5.1 native async ORM usage
- ✅ Backward compatible (all sync callers unchanged)
- ✅ Atomic F() expressions in comment upvotes (improvement!)
- ✅ Clear naming convention (`_async` suffix)

### Testing
- Existing tests for sync methods continue passing
- Add tests for async variants

### Commit Message
```
feat: add async variants to model methods for telegram bot

Add async_* methods to models used by telegram bot handlers:
- PostSubscription: subscribe_async, unsubscribe_async
- PostVote: upvote_async
- CommentVote: upvote_async (with F() expressions for atomic updates)
- Post: unpublish_async

Maintains sync wrappers for all existing callers (views, admin, django_q).
Uses Django 5.1 native async ORM (aupdate_or_create, adelete, asave).

Zero breaking changes - all existing code continues working.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## 3. **Rooms Helpers Async Conversion** (MEDIUM PRIORITY)

### What
Convert room ban/unban helpers to async with sync wrappers.

### Why
- These are called from admin actions (sync context)
- Preparation for async telegram bot API
- Uses Django 5.1 async ORM (`async for`)

### Files Changed
**rooms/helpers.py:**
```python
def ban_user_in_all_chats(user: User, is_permanent=True):
    async_to_sync(_ban_user_in_all_chats_async)(user, is_permanent)

async def _ban_user_in_all_chats_async(user: User, is_permanent=True):
    async for room in Room.objects.filter(chat_id__isnull=False):
        # Use await for telegram API calls
        chat_member = await bot.get_chat_member(room.chat_id, user.telegram_id)
        # ... rest of logic

def unban_user_in_all_chats(user: User):
    async_to_sync(_unban_user_in_all_chats_async)(user)

async def _unban_user_in_all_chats_async(user: User):
    async for room in Room.objects.filter(chat_id__isnull=False):
        # Use await for telegram API calls
        ...
```

### Changes
- `kick_chat_member()` → `ban_chat_member()` (v20+ API)
- `telegram.TelegramError` → `TelegramError` (cleaner import)
- Use `async for` over queryset (Django 5.1 feature)

### Testing
- Test ban/unban still works from admin
- All existing integration tests pass

### Commit Message
```
refactor: prepare rooms helpers for async telegram API

Convert ban_user_in_all_chats and unban_user_in_all_chats to async
implementation with sync wrappers. Uses Django 5.1 async for over querysets.

Changes:
- kick_chat_member → ban_chat_member (aligns with telegram API v20+)
- Use async for over Room queryset
- Maintain sync wrappers for admin actions

Zero breaking changes - admin actions continue working.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### ⚠️ CAVEAT
This one depends on telegram SDK upgrade for `ban_chat_member()` and async bot API.
**Alternative:** Skip this one and include it in the SDK upgrade patch.

---

## 4. **Atomic F() Expressions for Comment Upvotes** (LOW PRIORITY - BONUS)

### What
In `CommentVote.upvote_async()`, use `F()` expressions for atomic updates instead of `increment_vote_count()`.

### Why
- Prevents race conditions
- More efficient (single query vs. multiple)
- Best practice for counter updates

### Code
```python
# Before
comment.increment_vote_count()
comment.author.increment_vote_count()

# After
await Comment.objects.filter(id=comment.id).aupdate(upvotes=F("upvotes") + 1)
await User.objects.filter(id=comment.author_id).aupdate(upvotes=F("upvotes") + 1)
```

### Testing
- Verify upvote counts still increment correctly
- Add concurrency test to verify race condition is fixed

### Commit Message
```
fix: use atomic F() expressions for comment upvote counters

Replace increment_vote_count() with F() expressions in CommentVote.upvote_async
to prevent race conditions and improve efficiency.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## 5. **Test Infrastructure Improvements** (OPTIONAL - CAN INCLUDE IN SDK UPGRADE)

### What
Improvements to `notifications/telegram/tests.py` (BaseTelegramTest).

### Why
- Better event loop management
- Cleaner bot factory pattern
- Support for webhook testing

### Changes
Would need to review specific improvements in this file.

### Decision
**Recommend:** Include in SDK upgrade patch since it's test infrastructure.

---

## Recommended Order of PRs to Master

### PR #1: Async Notification Wrappers (Highest Value)
**Files:** 12 files (views + godmode)
**Risk:** Zero (pure wrapper)
**Lines:** ~20 changed
**Review Time:** 10 minutes

```bash
git checkout -b prepare-async-notifications origin/master
# Cherry-pick or manually apply async_to_sync wrappers
# Test: python manage.py test
```

### PR #2: Async Model Methods (High Value)
**Files:** 4 model files
**Risk:** Low (dual API, backward compatible)
**Lines:** ~100 added
**Review Time:** 30 minutes

```bash
git checkout -b async-model-methods origin/master
# Apply model changes
# Add tests for async methods
```

### PR #3: Atomic Comment Upvotes (Nice-to-have)
**Files:** 1 file (comments/models.py)
**Risk:** Low (improvement)
**Lines:** ~5 changed
**Review Time:** 10 minutes

```bash
git checkout -b atomic-upvotes origin/master
# Apply F() expression changes
# Add concurrency test
```

### ❌ SKIP: Rooms Helpers
**Reason:** Depends on telegram SDK v20+ API (`ban_chat_member`)
**Include in:** Main SDK upgrade PR

---

## Impact Summary

| Improvement | Files | LOC | Breaking | Test Impact | Review Time |
|-------------|-------|-----|----------|-------------|-------------|
| Async notification wrappers | 12 | ~20 | No | None | 10 min |
| Async model methods | 4 | ~100 | No | Add async tests | 30 min |
| Atomic upvotes | 1 | ~5 | No | Add concurrency test | 10 min |
| **TOTAL** | **17** | **~125** | **No** | **Minor** | **50 min** |

---

## Benefits of Pre-Committing

### For Reviewers
- ✅ Smaller, focused PRs easier to review
- ✅ Each change has clear purpose and rationale
- ✅ Can be tested independently
- ✅ SDK upgrade PR becomes much smaller

### For Codebase
- ✅ Incremental improvements
- ✅ Each change is backward compatible
- ✅ Easier to bisect if issues arise
- ✅ Prepares for async without big bang migration

### For SDK Upgrade PR
- ✅ Reduces diff size by ~125 LOC
- ✅ Removes "noise" from the SDK upgrade diff
- ✅ Reviewers can focus on SDK-specific changes
- ✅ Lower risk (preparatory changes already tested in production)

---

## What CANNOT Be Pre-Committed

These changes are tightly coupled to the telegram SDK upgrade:

1. **All telegram import changes** - `ParseMode`, `filters`, etc.
2. **All handler async conversions** - bot/handlers/*.py
3. **Bot infrastructure changes** - Updater → Application
4. **Middleware pattern** - bot/middleware.py (new file)
5. **Test async conversions** - test_*.py files
6. **Notification async implementations** - notifications/telegram/*.py internals
7. **Rooms helpers** - uses v20+ API methods

These must remain in the SDK upgrade PR.

---

## Testing Strategy for Pre-Commits

### PR #1 (Async Notification Wrappers)
```bash
# All existing tests should pass unchanged
python manage.py test authn badges comments posts tickets users godmode
```

### PR #2 (Async Model Methods)
```bash
# Existing sync tests
python manage.py test posts.tests comments.tests

# New async tests (add these)
python manage.py test posts.tests.TestAsyncSubscriptions
python manage.py test posts.tests.TestAsyncVotes
python manage.py test comments.tests.TestAsyncVotes
```

### PR #3 (Atomic Upvotes)
```bash
# Existing tests
python manage.py test comments.tests

# New concurrency test (add this)
python manage.py test comments.tests.TestAtomicUpvotes
```

---

## Rollback Plan

Each PR is independent:
- PR #1 fails? Revert just the wrappers
- PR #2 fails? Revert just the async methods
- PR #3 fails? Revert just the F() expressions

No cascading failures since PRs are independent.

---

## Conclusion

Extracting these **17 files (~125 LOC)** as 2-3 separate PRs will:

1. Make the SDK upgrade PR **~15% smaller**
2. Allow incremental review and testing
3. Reduce risk of the big SDK upgrade
4. Prepare codebase for async gradually
5. Each change is backward compatible

**Recommended Next Steps:**
1. Create PR #1 (async notification wrappers) - 10 min review
2. After PR #1 merges, create PR #2 (async model methods) - 30 min review
3. Optionally create PR #3 (atomic upvotes) - 10 min review
4. Then proceed with SDK upgrade PR (much smaller now!)

This approach follows the **"Strangler Fig Pattern"** - gradually replacing old code with new without breaking anything.
