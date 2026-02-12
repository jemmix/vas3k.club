# Telegram Test Suite Analysis

**Date**: 2026-02-11
**Branch**: telegram-upgrade
**Total Tests**: 274
**Passed**: 33
**Failed**: 71
**Errors**: 170

---

## Summary

The telegram test suite has 241 failing tests after the v20+ upgrade. Most failures fall into a few categories that can be fixed systematically.

---

## Failure Categories

### 1. **Bot Handler Tests** - Async DB Access Issues (170 errors)

**Root Cause**: Handler tests are calling async handlers, but Django DB operations are sync. The handlers need `@sync_to_async` wrappers or similar async-safe DB access patterns.

**Example Error**:
```
ERROR: test_success_approved_user (bot.handlers.test_auth.CommandAuthTest.test_success_approved_user)
Traceback:
  File "/bot/handlers/auth.py", line 23, in command_auth
    user = User.objects.filter(secret_hash=secret_code).first()
```

**Affected Test Files** (by module):
- `bot.handlers.test_auth` - 8 errors (auth command tests)
- `bot.handlers.test_comments` - 8 errors (comment creation tests)
- `bot.handlers.test_common` - 15 errors (helper function tests)
- `bot.handlers.test_fun` - 6 errors (fun commands)
- `bot.handlers.test_llm` - 7 errors (LLM response tests)
- `bot.handlers.test_moderation` - 13 errors (moderation callbacks)
- `bot.handlers.test_posts` - 5 errors (subscribe/unsubscribe)
- `bot.handlers.test_top` - 4 errors (top command)
- `bot.handlers.test_upvotes` - 18 errors (upvote handlers)
- `bot.handlers.test_whois` - 6 errors (whois command)
- `bot.test_decorators` - 10 errors (decorator tests)
- `helpdeskbot.handlers.test_*` - 20 errors (helpdesk handlers)
- `helpdeskbot.test_help_desk_common` - 6 errors (common functions)

**Total**: ~170 errors

**Fix Strategy**:
1. **Option A**: Add `@sync_to_async` decorator from Django's asgiref to all DB access in handlers
2. **Option B**: Use `sync_to_async()` wrapper around DB operations inline
3. **Option C**: Create async-safe helper methods that wrap DB access

**Recommended**: Option B - minimal changes, explicit async/sync boundary

---

### 2. **Notification Tests** - Request Not Sent Issues (71 failures)

**Root Cause**: Tests expect synchronous `send_telegram_message()` to make HTTP requests immediately, but the notification system now uses async wrappers with `asyncio.run()`, which may have timing issues or the mock server isn't catching requests properly.

**Example Error**:
```
FAIL: test_send_telegram_message_text (notifications.telegram.tests.SendTelegramMessageTest.test_send_telegram_message_text)
AssertionError: False is not true : some requests not executed: [ExpectedRequest(...)]
```

**Affected Test Files**:
- `notifications.telegram.tests.SendTelegramMessageTest` - 18 failures (core notification tests)
- `notifications.telegram.test_comments` - 16 failures
- `notifications.telegram.test_posts` - 25 failures
- `notifications.telegram.test_achievements` - 8 failures
- `notifications.telegram.test_badges` - 2 failures
- `notifications.telegram.test_users` - 2 failures

**Total**: ~71 failures

**Fix Strategy**:
The issue is that `asyncio.run()` creates a new event loop each time, and the mock server may not be compatible. Solutions:
1. Make notification tests fully async (test methods become `async def`)
2. Ensure mock server is compatible with nested event loops
3. Add better synchronization between async notification calls and test assertions

**Recommended**: Make notification tests async - aligns with v20+ patterns

---

### 3. **Import Errors** - Missing Modules (2 errors)

**Root Cause**: Test modules trying to import `Filters` (old v12 API) instead of `filters` (new v20+ API)

**Affected**:
- `rooms.management.commands.test_count_chat_members`
- `rooms.test_helpers`

**Fix Strategy**: Update imports from `Filters` → `filters`

---

## Work Plan - Organized by Chunks

### **Chunk 1: Fix Import Errors** ⚡ Quick Win
**Est. Time**: 15 minutes
**Files**: 2
**Impact**: Fixes 2 tests

1. Fix `rooms.management.commands.test_count_chat_members.py`
2. Fix `rooms.test_helpers.py`

Search/replace: `from telegram.ext import Filters` → `from telegram.ext import filters`

---

### **Chunk 2: Fix Notification System Tests** 🔧 Core Infrastructure
**Est. Time**: 4-6 hours
**Files**: ~15 test files
**Impact**: Fixes 71 tests

**Phase 2.1**: Update SendTelegramMessageTest (base class)
- Convert test methods to `async def`
- Ensure proper async/await usage with mock server
- Fix event loop coordination

**Phase 2.2**: Update notification test modules
- `notifications/telegram/test_comments.py`
- `notifications/telegram/test_posts.py`
- `notifications/telegram/test_achievements.py`
- `notifications/telegram/test_badges.py`
- `notifications/telegram/test_users.py`
- `notifications/telegram/test_ban.py`

**Files to modify**:
- `notifications/telegram/tests.py` - BaseTelegramTest, SendTelegramMessageTest
- `notifications/telegram/test_*.py` - All notification test modules

---

### **Chunk 3: Fix Bot Handler Tests** 🔨 Major Work
**Est. Time**: 8-12 hours
**Files**: ~25 test files
**Impact**: Fixes 170 tests

**Phase 3.1**: Create async DB helper pattern
```python
from asgiref.sync import sync_to_async

# Example pattern for handlers
async def command_auth(update: Update, context: CallbackContext):
    secret_code = update.message.text.split(" ", 1)[1].strip()

    # Wrap DB access in sync_to_async
    user = await sync_to_async(
        lambda: User.objects.filter(secret_hash=secret_code).first()
    )()

    if not user:
        await update.effective_chat.send_message("User not found")
        return

    # ... rest of handler
```

**Phase 3.2**: Update handlers systematically
1. **Priority 1** (most used):
   - `bot/handlers/common.py` - Helper functions used by all
   - `bot/decorators.py` - Decorators used by all handlers

2. **Priority 2** (simple handlers):
   - `bot/handlers/auth.py`
   - `bot/handlers/whois.py`
   - `bot/handlers/fun.py`
   - `bot/handlers/top.py`

3. **Priority 3** (complex handlers):
   - `bot/handlers/comments.py`
   - `bot/handlers/upvotes.py`
   - `bot/handlers/posts.py`
   - `bot/handlers/moderation.py`
   - `bot/handlers/llm.py`

**Phase 3.3**: Update helpdesk handlers
- `helpdeskbot/handlers/question.py`
- `helpdeskbot/handlers/answers.py`
- `helpdeskbot/help_desk_common.py`

**Files to modify**:
- All handler files in `bot/handlers/`
- All handler files in `helpdeskbot/handlers/`
- All test files: `bot/handlers/test_*.py`
- All test files: `helpdeskbot/handlers/test_*.py`

---

## Detailed Breakdown by Module

| Module | Tests | Errors | Failures | Pass % | Notes |
|--------|-------|--------|----------|--------|-------|
| bot.test_integration | 2 | 0 | 0 | 100% | ✅ Fixed |
| helpdeskbot.test_integration | 2 | 0 | 0 | 100% | ✅ Fixed |
| bot.handlers.test_auth | 8 | 8 | 0 | 0% | DB access issues |
| bot.handlers.test_comments | 8 | 8 | 0 | 0% | DB access issues |
| bot.handlers.test_common | 15 | 15 | 0 | 0% | DB access issues |
| bot.handlers.test_fun | 6 | 6 | 0 | 0% | DB access issues |
| bot.handlers.test_llm | 7 | 7 | 0 | 0% | DB access issues |
| bot.handlers.test_moderation | 13 | 13 | 0 | 0% | DB access issues |
| bot.handlers.test_posts | 5 | 5 | 0 | 0% | DB access issues |
| bot.handlers.test_top | 4 | 4 | 0 | 0% | DB access issues |
| bot.handlers.test_upvotes | 18 | 18 | 0 | 0% | DB access issues |
| bot.handlers.test_whois | 6 | 6 | 0 | 0% | DB access issues |
| bot.test_decorators | 10 | 10 | 0 | 0% | DB access issues |
| helpdeskbot.handlers.test_* | 20 | 20 | 0 | 0% | DB access issues |
| helpdeskbot.test_help_desk_common | 6 | 6 | 0 | 0% | DB access issues |
| notifications.telegram.tests | 18 | 0 | 18 | 0% | Request not sent |
| notifications.telegram.test_comments | 16 | 0 | 16 | 0% | Request not sent |
| notifications.telegram.test_posts | 25 | 0 | 25 | 0% | Request not sent |
| notifications.telegram.test_achievements | 8 | 0 | 8 | 0% | Request not sent |
| notifications.telegram.test_badges | 2 | 0 | 2 | 0% | Request not sent |
| notifications.telegram.test_users | 2 | 0 | 2 | 0% | Request not sent |
| rooms.* | 2 | 2 | 0 | 0% | Import errors |

---

## Recommended Execution Order

1. **Chunk 1** (15 min) - Fix import errors - gets 2 tests passing quickly
2. **Chunk 3, Phase 3.1** (2 hours) - Fix common.py and decorators - unlocks many tests
3. **Chunk 3, Phase 3.2** (6-8 hours) - Fix handlers systematically
4. **Chunk 2** (4-6 hours) - Fix notification tests
5. **Chunk 3, Phase 3.3** (2 hours) - Fix helpdesk handlers

**Total Estimated Time**: 14-18 hours

---

## Critical Files to Fix First

1. **`bot/handlers/common.py`** - Used by all bot handlers
2. **`bot/decorators.py`** - Used by all protected handlers
3. **`notifications/telegram/tests.py`** - Base class for all notification tests
4. **`notifications/telegram/common.py`** - Core notification system

Fixing these 4 files will unlock the majority of tests.

---

## Success Metrics

- **Target**: 100% tests passing (274/274)
- **Milestone 1**: Fix imports (2 tests) → 35/274 passing (13%)
- **Milestone 2**: Fix common helpers (100 tests) → 135/274 passing (49%)
- **Milestone 3**: Fix all handlers (70 tests) → 205/274 passing (75%)
- **Milestone 4**: Fix notifications (71 tests) → 274/274 passing (100%)

---

## Known Issues & Notes

1. **Database access in async context**: Django ORM is synchronous, requires `sync_to_async` wrapper
2. **Mock server compatibility**: May need to ensure threading/async compatibility
3. **Event loop nesting**: `asyncio.run()` in tests creates nested loops, may need coordination
4. **Decorator async conversion**: All decorators need async/await support

---

## Next Steps

1. Start with Chunk 1 (import errors) - quick win
2. Fix bot/handlers/common.py and decorators - unlocks many tests
3. Work through handlers systematically
4. Fix notification tests
5. Run full suite and verify 100% passing
6. Commit and push to jemmix after each chunk
