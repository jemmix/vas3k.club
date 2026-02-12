#!/usr/bin/env python3
"""
Script to convert telegram test files to async/await pattern for python-telegram-bot v22.6
"""
import re
import sys
from pathlib import Path


def convert_test_file(file_path: Path) -> tuple[int, str]:
    """
    Convert a test file to async/await pattern.

    Returns:
        Tuple of (number_of_methods_converted, conversion_log)
    """
    content = file_path.read_text()
    original_content = content

    log = []
    methods_converted = 0

    # Pattern to match test methods
    # Matches: "def test_..." or "@patch...\n    def test_..."
    # Including methods with decorators
    test_method_pattern = r'((?:    @[^\n]+\n)*)(    def )(test_[a-zA-Z_0-9]+)(\(self[^)]*\):)'

    def replace_test_method(match):
        nonlocal methods_converted
        decorators = match.group(1)
        def_keyword = match.group(2)
        method_name = match.group(3)
        params = match.group(4)

        # Skip if already async
        if 'async def' in def_keyword:
            return match.group(0)

        methods_converted += 1
        log.append(f"  - {method_name}")

        # Convert to async def
        return f"{decorators}{def_keyword}async {method_name}{params}"

    # Convert test method signatures
    content = re.sub(test_method_pattern, replace_test_method, content)

    # Find all handler/function calls that need await
    # Common patterns in the codebase
    handler_calls = [
        r'\b(command_auth|command_horo|command_random|command_help)\(',
        r'\b(reply_to_comment|comment_to_post|comment)\(',
        r'\b(on_post_subscription_button|on_post_unsubscription_button)\(',
        r'\b(on_upvote|upvote_comment|upvote_post|on_upvote_reply)\(',
        r'\b(on_post_approve|on_post_forgive|on_post_reject)\(',
        r'\b(on_user_approve|on_user_reject)\(',
        r'\b(on_help_command|on_start_question|on_reply_message)\(',
        r'\b(whois|command_top)\(',
        r'\b(on_message)\(',
    ]

    # Add await before handler calls (but not in comments or already awaited)
    for pattern in handler_calls:
        # Look for calls that are NOT already awaited and NOT in comments
        # This is a simplified approach - match the function call and add await if not present
        def add_await(match):
            full_match = match.group(0)
            # Check if already has await
            # Look back in the line to see if 'await' appears before this match
            return full_match  # Will handle manually in second pass

        # We'll do a simpler replacement: find lines with these calls
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            # Skip comment lines
            if line.strip().startswith('#') or line.strip().startswith('"""') or line.strip().startswith("'''"):
                new_lines.append(line)
                continue

            # Check if line contains a handler call
            for pattern in handler_calls:
                if re.search(pattern, line):
                    # Check if already has await
                    if 'await ' not in line and '= ' in line and '(' in line:
                        # Pattern: result = handler(...)
                        line = re.sub(r'(\s+)(\w+)\s*=\s*(' + pattern[3:], r'\1\2 = await \3', line)
                    elif 'await ' not in line and '(' in line:
                        # Pattern: handler(...)
                        line = re.sub(r'(\s+)(' + pattern[3:], r'\1await \2', line)
                    break

        new_lines.append(line)
        content = '\n'.join(new_lines)

    # Save if changed
    if content != original_content:
        file_path.write_text(content)
        return methods_converted, '\n'.join(log)
    else:
        return 0, "No changes needed"


def main():
    # List of all test files to convert
    test_files = [
        # Bot handler tests
        "bot/handlers/test_auth.py",
        "bot/handlers/test_comments.py",
        "bot/handlers/test_common.py",
        "bot/handlers/test_fun.py",
        "bot/handlers/test_llm.py",
        "bot/handlers/test_moderation.py",
        "bot/handlers/test_posts.py",
        "bot/handlers/test_top.py",
        "bot/handlers/test_upvotes.py",
        "bot/handlers/test_whois.py",
        # Bot infrastructure
        "bot/test_decorators.py",
        "bot/test_integration.py",
        # Helpdesk tests
        "helpdeskbot/handlers/test_answers.py",
        "helpdeskbot/handlers/test_question.py",
        "helpdeskbot/test_help_desk_common.py",
        "helpdeskbot/test_integration.py",
        # Notification tests
        "notifications/telegram/test_achievements.py",
        "notifications/telegram/test_badges.py",
        "notifications/telegram/test_ban.py",
        "notifications/telegram/test_comments.py",
        "notifications/telegram/test_moderation.py",
        "notifications/telegram/test_muted.py",
        "notifications/telegram/test_posts.py",
        "notifications/telegram/test_users.py",
        "notifications/telegram/tests.py",
    ]

    base_path = Path("/Users/andy/projects/vas3k.club")

    total_methods = 0
    total_files = 0

    print("Converting telegram test files to async/await pattern...")
    print("=" * 70)

    for rel_path in test_files:
        file_path = base_path / rel_path
        if not file_path.exists():
            print(f"\n❌ {rel_path} - FILE NOT FOUND")
            continue

        methods, log = convert_test_file(file_path)
        if methods > 0:
            print(f"\n✓ {rel_path}")
            print(f"  Converted {methods} test methods")
            if log:
                print(log)
            total_methods += methods
            total_files += 1
        else:
            print(f"\n- {rel_path} - {log}")

    print("\n" + "=" * 70)
    print(f"Summary: Converted {total_methods} test methods in {total_files} files")


if __name__ == "__main__":
    main()
