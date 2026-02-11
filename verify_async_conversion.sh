#!/bin/bash
# Script to verify async/await conversion of telegram tests

echo "Verifying async/await conversion for telegram tests..."
echo "=" | tr '=' '=' | awk '{for(i=1;i<=70;i++)printf "="; printf "\n"}'

# Count async test methods
ASYNC_COUNT=$(grep -r "async def test_" bot/handlers/test_*.py bot/test_*.py helpdeskbot notifications/telegram 2>/dev/null | wc -l | tr -d ' ')
echo "✓ Async test methods found: $ASYNC_COUNT"

# Check for any remaining non-async test methods (should be 0)
SYNC_COUNT=$(grep -rn "^\s\+def test_" bot/handlers/test_*.py bot/test_*.py helpdeskbot notifications/telegram 2>/dev/null | wc -l | tr -d ' ')
if [ "$SYNC_COUNT" -eq 0 ]; then
    echo "✓ No synchronous test methods remaining: PASS"
else
    echo "✗ Found $SYNC_COUNT synchronous test methods: FAIL"
    grep -rn "^\s\+def test_" bot/handlers/test_*.py bot/test_*.py helpdeskbot notifications/telegram 2>/dev/null | head -10
fi

# Verify handler calls have await
AWAIT_PATTERNS=(
    "await command_auth"
    "await command_horo"
    "await command_random"
    "await reply_to_comment"
    "await comment_to_post"
    "await upvote_comment"
    "await upvote_post"
    "await command_top"
    "await command_whois"
    "await llm_response"
)

echo ""
echo "Checking handler calls have 'await':"
for pattern in "${AWAIT_PATTERNS[@]}"; do
    count=$(grep -r "$pattern" bot/handlers/test_*.py 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
        echo "  ✓ $pattern: $count occurrences"
    fi
done

echo ""
echo "=" | tr '=' '=' | awk '{for(i=1;i<=70;i++)printf "="; printf "\n"}'
echo "Conversion verification complete!"
echo ""
echo "To run tests:"
echo "  python manage.py test --tag telegram"
