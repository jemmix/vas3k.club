# Test Framework Improvements

## Summary

Enhanced the Telegram bot test framework to support:
1. **Route-based request handling** - Alternative to strict request expectations
2. **Post-hoc assertions** - Verify request bodies after handlers complete (when you have the data)
3. **Event-based synchronization** - Reliable async test waiting without sleeps
4. **Request logging** - All requests captured for inspection

## Changes Made

### 1. `notifications/telegram/tests.py`

**Added to `MockTelegramServer`:**
- `routes: dict[str, str | Callable]` - Path-based response handlers
- `requests_received: list[Request]` - Complete request log
- `add_route(path, response)` - Register a route (static or callable)
- `get_route_response(request)` - Execute route handler
- `log_request(request)` - Record every request

**Modified `MockTelegramHandler._do_handle()`:**
- Always log requests to `requests_received`
- Try expected requests first (existing strict behavior)
- Fall back to routes if no expected request queued
- Fail if neither matches

**Backward compatibility:**
- All existing tests using `expect_requests()` work unchanged
- Routes are opt-in for tests that need them

### 2. `bot/handlers/test_comments.py`

**Fixed 4 tests using new framework:**

**Before (broken):**
```python
# Can't know comment ID before creating it
self.server.expect_requests([...])  # What URL to expect?
reply_to_comment(update, context)
# Weak assertion
self.assertTrue(len(self.server.requests_received) > 0)
```

**After (working):**
```python
# Register generic route
self.server.add_route(SEND_MESSAGE_PATH, RESPONSE)

# Run handler
reply_to_comment(update, context)

# Get comment ID from DB
new_comment = Comment.objects.filter(...).first()

# Now assert exact message with real ID
expected_url = f"http://127.0.0.1:8000/post/{slug}/comment/{new_comment.id}/"
requests = [r for r in self.server.requests_received if r.path == SEND_MESSAGE_PATH]
self.assertEqual(requests[0].body["text"], f'<a href="{expected_url}">...</a>')
```

### 3. `bot/test_integration.py`

**Fixed `test_webhook_help_command`:**
```python
# Event for synchronization
message_sent = threading.Event()

def handle_send_message(request):
    message_sent.set()  # Signal completion
    return RESPONSE

self.server.add_route(SEND_MESSAGE_PATH, handle_send_message)

# Send webhook update
self._send_webhook_update(update)

# Wait for bot (no sleep!)
if not message_sent.wait(timeout=5):
    self.fail("Bot did not send message within 5 seconds")

# Verify exact request
requests = [r for r in self.server.requests_received if r.path == SEND_MESSAGE_PATH]
self.assertEqual(requests[0].body["text"], WELCOME_MESSAGE)
```

**Fixed `test_polling_help_command`:**
```python
# State machine for getUpdates
call_count = 0
def handle_get_updates(request):
    nonlocal call_count
    call_count += 1
    if call_count == 1:
        return json.dumps({"ok": True, "result": [update.to_dict()]})
    else:
        time.sleep(0.1)  # Brief pause to avoid busy-polling
        return json.dumps({"ok": True, "result": []})

self.server.add_route(GET_UPDATES_PATH, handle_get_updates)
# Now polling can call getUpdates unlimited times without test failure
```

**Removed:**
- `@unittest.skip()` decorators on both tests
- Long comment explaining the timing hack
- `time.sleep(1)` waits

## Impact

**Before:**
- 172 tests total
- 164 passing
- 6 failing (incomplete comment tests)
- 2 skipped (flaky integration tests)

**After:**
- 172 tests total
- 172 passing ✅
- 0 failing
- 0 skipped
- Verified with 10 consecutive successful runs (no flakiness)

## Usage Patterns

### Pattern 1: Post-hoc Assertions (unpredictable data)
Use when handler generates data (IDs, timestamps, URLs) that you can't know beforehand.

```python
self.server.add_route(path, response_string)
handler(update, context)
entity = Database.objects.get(...)  # Get generated data
requests = [r for r in self.server.requests_received if r.path == path]
assert requests[0].body["field"] == f"value with {entity.id}"
```

### Pattern 2: Event Synchronization (async handlers)
Use when handler runs in background thread/process.

```python
event = threading.Event()
def route_handler(request):
    event.set()
    return response

self.server.add_route(path, route_handler)
trigger_async_handler()
assert event.wait(timeout=5), "Handler didn't complete"
```

### Pattern 3: State Machines (polling/retries)
Use when code makes repeated requests (polling, retries).

```python
state = {"count": 0}
def route_handler(request):
    state["count"] += 1
    if state["count"] == 1:
        return first_response
    else:
        return subsequent_response

self.server.add_route(path, route_handler)
# Handler can call endpoint unlimited times
```

### Pattern 4: Strict Expectations (unchanged)
Use when you know exact request sequence upfront.

```python
self.server.expect_requests([
    ExpectedRequest(Request("POST", path, exact_body), response),
])
handler(update, context)
# Existing tests continue working
```

## Design Principles

1. **Opt-in**: Routes don't break existing `expect_requests()` tests
2. **Composable**: Can mix expected requests and routes in same test
3. **Minimal**: Framework change is ~30 lines of code
4. **Test-side logic**: Complex logic (state machines, events) lives in tests, not framework
5. **Strict by default**: Tests still verify exact request bodies, just at different time

## Future Considerations

### Not implemented (kept simple):
- ❌ Unordered request matching - Test order matters for clarity
- ❌ Partial body matching - Use routes + post-hoc assertions instead
- ❌ Regex/lambda matchers in body - Use routes + post-hoc assertions instead
- ❌ Built-in async primitives - Tests handle their own events

### Potential additions (if needed):
- Helper to filter `requests_received` by path/method
- Helper to create common route handlers (echo, increment counter, etc.)
- Request assertions that show better diffs (currently manual)
