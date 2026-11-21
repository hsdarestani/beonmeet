#!/usr/bin/env python3
"""Stale user notice and terminal lifecycle regression."""
import ast
from pathlib import Path
root=Path(__file__).resolve().parents[1]
code=(root/"app/main.py").read_text(encoding="utf-8")
i18n=(root/"app/i18n.py").read_text(encoding="utf-8")
tree=ast.parse(code)
join=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="join_progress_loop")
clean=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="state_cleanup_loop")
jp=ast.get_source_segment(code,join) or ""
cl=ast.get_source_segment(code,clean) or ""
assert 'if age_seconds > 360:' in jp
assert jp.index('if age_seconds > 360:') < jp.index('await tg_text(')
assert 'if not key or launched.get(key):' in jp
assert 'expired_unconfirmed_chats: list[str] = []' in cl
assert 'status in {"joining", "remote_claimed", "waiting_for_admission"}' in cl
assert 'and not (launched or {}).get("recording_started_at")' in cl
assert 'now - created <= max_age + timedelta(minutes=15)' in cl
assert 'expired_unconfirmed_chats.append(chat_id)' in cl
assert cl.index('await save_state()') < cl.index('for chat_id in expired_unconfirmed_chats:')
assert 't(chat_id, "join_expired_without_recording")' in cl
assert 'credit_entries' not in cl
assert 'wallet_charge' not in cl
assert i18n.count('"join_expired_without_recording"')==3
print("STALE_JOIN_NOTIFICATION_LIFECYCLE_TEST_PASS")
