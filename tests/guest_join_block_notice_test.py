#!/usr/bin/env python3
"""Guest admission guidance must be truthful, once-only and wallet-neutral."""
from pathlib import Path
import ast

root=Path(__file__).resolve().parents[1]
main=(root/"app/main.py").read_text(encoding="utf-8")
translations=(root/"app/i18n.py").read_text(encoding="utf-8")
tree=ast.parse(main)
progress=next(x for x in tree.body if isinstance(x,ast.AsyncFunctionDef) and x.name=="join_progress_loop")
source=ast.get_source_segment(main,progress)
assert source
assert '"join_access_notice_at" if age_seconds >= 180' in source
assert '"join_slow_notified_at" if age_seconds >= 90' in source
assert '"join_connecting_notified_at" if age_seconds >= 12' in source
assert 'if not key or launched.get(key):' in source
assert '"join_access_notice_at": "join_guest_access_possible"' in source
assert 'current[key] = datetime.now(timezone.utc).isoformat()' in source
assert translations.count('"join_guest_access_possible"')==3
assert translations.count("Meeting access")>=3
assert "record_recording" not in source
assert "seconds_delta" not in source
assert "credit_entries" not in source
print("ANONYMOUS_MEET_ADMISSION_NOTICE_TEST_PASS")
