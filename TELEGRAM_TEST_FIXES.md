# Telegram Test Failures - Analysis & Fix Plan

## Current Status
- **Total tests:** 172
- **Passing:** 159 (92.4%)
- **Failing:** 11 (10 errors + 1 failure)
- **Skipped:** 2 (flaky integration tests)

---

## Category 1: Database Connection Errors (8 tests)

### Affected Files
- `bot/handlers/test_comments.py` - 7 tests
- Partial failures in tearDown methods

### Root Cause
The handlers in `bot/handlers/comments.py` call functions that invoke `close_old_connections()`, which closes the DB connection during tests. The mock for `close_old_connections` is missing or incorrectly scoped.

### Failing Tests
1. `test_creates_reply_comment` (ReplyToCommentTest)
2. `test_creates_top_level_comment` (CommentToPostTest)
3. `test_rejects_rate_limited_user` (ReplyToCommentTest)
4. `test_rejects_short_comment` (CommentToPostTest)
5. `test_routes_to_comment_to_post` (CommentRouterTest)
6. `test_routes_to_reply_to_comment` (CommentRouterTest)
7. `test_skips_reply_to_other_user` (CommentRouterTest)

### Error Pattern
```python
django.db.utils.OperationalError: the connection is closed
```

Occurs when:
- Handler code calls `get_club_user()` → `close_old_connections()`
- Handler code calls `get_club_comment()` → `close_old_connections()`
- Handler code calls `get_club_post()` → `close_old_connections()`
- tearDown tries to delete test data from closed connection

### Fix Strategy

**Option A: Add Missing Patches (RECOMMENDED)**
```python
# In setUp() of affected test classes
self.close_old_connections_patch = patch("bot.handlers.common.close_old_connections")
self.close_old_connections_patch.start()

# In tearDown()
self.close_old_connections_patch.stop()
```

This is the pattern used successfully in:
- `bot/handlers/test_upvotes.py` ✅
- `bot/handlers/test_common.py` ✅
- `bot/handlers/test_posts.py` ✅

**Why this works:**
- Mocking `close_old_connections()` prevents it from actually closing the DB connection
- Tests can complete their DB operations in both the handler and tearDown
- No changes needed to production code

**Implementation checklist:**
- [ ] Add patch to `CommentRouterTest`
- [ ] Add patch to `ReplyToCommentTest`
- [ ] Add patch to `CommentToPostTest`

**Estimated effort:** 10 minutes

---

## Category 2: Text Mismatch (1 test)

### Affected File
- `bot/handlers/test_posts.py::UnsubscribeTest::test_handles_already_unsubscribed`

### Root Cause
**Known issue documented in TELEGRAM_TEST_STATUS.md:**

Production code has typo at `bot/handlers/posts.py:60`:
```python
text=f"Вы отписались от о комментариев к посту «{post.title}» 🔕"
#                        ^ extra "о"
```

Test expects the same typo at `test_posts.py:125`:
```python
"text": f"Вы отписались от о комментариев к посту «{post.title}» 🔕",
#                           ^ matches typo
```

### Fix Strategy

**Option A: Fix Typo in Production + Update Test (RECOMMENDED)**
1. Remove extra "о" in `bot/handlers/posts.py:60`
2. Update test expectation in `test_posts.py:125`

**Before:**
```python
# posts.py:60
text=f"Вы отписались от о комментариев к посту «{post.title}» 🔕"
```

**After:**
```python
# posts.py:60
text=f"Вы отписались от комментариев к посту «{post.title}» 🔕"
```

**Option B: Fix Test to Match Typo**
Just update `test_posts.py:125` to match current (incorrect) production text.
- ❌ Not recommended - perpetuates the typo

**Estimated effort:** 2 minutes

---

## Category 3: Flaky Integration Tests (2 tests)

### Affected File
- `bot/test_integration.py`

### Skipped Tests
1. `test_webhook_help_command` - Webhook mode integration test
2. `test_polling_help_command` - Polling mode integration test

### Root Cause
**Race condition in async processing:**
```python
# Current approach in test
webhook_server.send_update(update)
time.sleep(1)  # ❌ Unreliable wait
# Expect response to be ready
```

The `time.sleep(1)` is a brittle timing assumption:
- May be too short on slow CI systems → test fails
- May be too long on fast systems → test is slow
- Doesn't scale with system load

### Why It's Flaky
1. Webhook receives Update via HTTP POST
2. Bot processes Update asynchronously
3. Bot makes Telegram API call (to mock server)
4. Test checks if call was made
5. **Problem:** Step 3 might not complete within 1 second

### Fix Strategy

**Option A: Event-Based Synchronization (RECOMMENDED)**
Use threading events instead of sleep:

```python
import threading

class ImprovedMockServer:
    def __init__(self):
        self.request_received_event = threading.Event()

    def do_POST(self):
        # ... handle request ...
        self.request_received_event.set()  # Signal request received

# In test:
webhook_server.send_update(update)
# Wait up to 5 seconds for response
if not server.request_received_event.wait(timeout=5):
    self.fail("Bot did not respond within timeout")
```

**Benefits:**
- ✅ Tests finish as soon as response arrives (faster)
- ✅ Reliable timeout prevents hanging
- ✅ Clear failure message when timeout occurs

**Option B: Polling with Exponential Backoff**
```python
import time

def wait_for_request(server, timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        if server.has_received_request():
            return True
        time.sleep(0.1)  # Check every 100ms
    return False
```

**Option C: Increase Timeout + Mark as Slow**
```python
@unittest.skipIf(os.getenv("FAST_TESTS"), "Slow integration test")
def test_webhook_help_command(self):
    # ...
    time.sleep(5)  # More generous timeout
```
- ❌ Still flaky, just less frequent
- ❌ Tests are slower

**Recommended: Option A**

**Implementation checklist:**
- [ ] Add `threading.Event()` to mock server
- [ ] Signal event when request received
- [ ] Replace `time.sleep(1)` with `event.wait(timeout=5)`
- [ ] Add clear failure messages on timeout
- [ ] Remove `@unittest.skip` decorators
- [ ] Test on CI to verify reliability

**Estimated effort:** 30-45 minutes

---

## Category 4: Testing Framework Limitations

### Current Framework Strengths
✅ **Mock HTTP Server** - Excellent for testing Telegram API calls
✅ **BaseTelegramTest** - Good foundation for bot handler tests
✅ **Helper Functions** - `create_test_user`, `create_callback_query_update`, etc.
✅ **Isolation** - Each test has clean database state

### Identified Limitations

#### 1. **Database Connection Management**
**Problem:** Must manually patch `close_old_connections` in every test class
**Impact:** Easy to forget, causes cryptic errors
**Root cause:** Django 5+ aggressively closes idle connections

**Improvement Options:**

**Option A: Base Test Class with Auto-Patching**
```python
class BotHandlerTestCase(BaseTelegramTest, TestCase):
    """Base class for bot handler tests - auto-patches close_old_connections"""

    def setUp(self):
        super().setUp()
        self.close_conn_patch = patch("bot.handlers.common.close_old_connections")
        self.close_conn_patch.start()

    def tearDown(self):
        super().tearDown()
        self.close_conn_patch.stop()

# Usage
class MyHandlerTest(BotHandlerTestCase):
    # No need to manually patch!
    pass
```

**Option B: Test Decorator**
```python
def with_stable_db_connection(test_class):
    """Decorator to auto-patch close_old_connections"""
    original_setup = test_class.setUp
    original_teardown = test_class.tearDown

    def new_setup(self):
        original_setup(self)
        self._db_patch = patch("bot.handlers.common.close_old_connections")
        self._db_patch.start()

    def new_teardown(self):
        self._db_patch.stop()
        original_teardown(self)

    test_class.setUp = new_setup
    test_class.tearDown = new_teardown
    return test_class

# Usage
@with_stable_db_connection
class MyHandlerTest(BaseTelegramTest, TestCase):
    pass
```

**Option C: pytest Fixture (if migrating to pytest)**
```python
@pytest.fixture(autouse=True)
def stable_db_connection():
    with patch("bot.handlers.common.close_old_connections"):
        yield
```

**Recommendation:** Option A (minimal change, clear inheritance)

#### 2. **Request Matching Strictness**
**Problem:** Minor text differences cause "Request mismatch" with limited debug info
**Current behavior:**
```
AssertionError: False is not true : some requests were unsuccessful
```

**Improvement:**
Add better diff output in `notifications/telegram/tests.py`:
```python
def _do_handle(self, request):
    # ... existing code ...
    if request.body != expected_request.request.body:
        # Show detailed diff
        import difflib
        diff = '\n'.join(difflib.unified_diff(
            json.dumps(expected_request.request.body, indent=2).splitlines(),
            json.dumps(request.body, indent=2).splitlines(),
            lineterm='',
            fromfile='expected',
            tofile='actual'
        ))
        log.error(f"Request body mismatch:\n{diff}")
```

**Benefit:** Immediately see what field mismatches

#### 3. **No Built-in Async Support**
**Problem:** Integration tests use `time.sleep()` for async operations
**Impact:** Flaky tests, slow test suite

**Options:**
- Add event-based synchronization (see Category 3)
- Consider pytest-asyncio if doing major refactor
- Add retry logic with exponential backoff

**Recommendation:** Event-based sync (already covered in Category 3)

#### 4. **Limited Coverage Reporting**
**Problem:** No clear visibility into which handlers/paths are untested

**Improvement:**
```bash
# Add to test commands
pipenv run coverage run manage.py test --tag telegram
pipenv run coverage report --include="bot/*,notifications/telegram/*"
pipenv run coverage html  # Visual report
```

**Benefit:** Identify gaps in test coverage

---

## Implementation Priority

### Phase 1: Quick Wins (15 minutes)
1. ✅ **Fix typo in posts.py** (Category 2)
   - Fix production code
   - Update test expectation
   - Verify test passes

2. ✅ **Add missing patches** (Category 1)
   - Add `close_old_connections` patches to test_comments.py
   - Verify all 7 tests pass

**Expected result:** 170/172 tests passing (99%)

### Phase 2: Framework Improvements (1-2 hours)
1. 🔧 **Create BotHandlerTestCase base class**
   - Implement auto-patching
   - Migrate existing tests gradually
   - Document usage

2. 🔧 **Fix integration test flakiness** (Category 3)
   - Add event-based synchronization
   - Remove sleeps
   - Un-skip tests
   - Verify on CI

**Expected result:** 172/172 tests passing (100%)

### Phase 3: Nice-to-Have (2-3 hours)
1. 📊 **Add coverage reporting**
2. 🐛 **Improve error messages** in test framework
3. 📚 **Document testing patterns** in README

---

## Success Metrics

- ✅ All 172 tests passing
- ✅ No skipped tests
- ✅ Tests complete in < 1 minute
- ✅ Zero flaky tests on CI
- ✅ Clear error messages when tests fail
- ✅ 90%+ code coverage for bot handlers

---

## Risk Assessment

### Low Risk
- ✅ Adding missing patches (proven pattern)
- ✅ Fixing typo (cosmetic change)

### Medium Risk
- ⚠️ Event-based synchronization (requires testing on CI)
- ⚠️ Base test class (affects all future tests)

### High Risk
- ❌ None identified

---

## Recommendations

**For immediate commit:**
1. Fix Category 1 (patches) + Category 2 (typo)
2. This gets to 170/172 passing with minimal risk
3. Can be done and tested in < 20 minutes

**For follow-up PR:**
1. Fix Category 3 (integration tests)
2. Add base test class
3. Add coverage reporting
4. Requires more testing but provides long-term value

**Timeline:**
- Phase 1: Today (15 min)
- Phase 2: This week (1-2 hours)
- Phase 3: Next week (2-3 hours)
