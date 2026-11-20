#!/usr/bin/env python3
"""Guard Persian-first Telegram onboarding, localized defaults, and saved choices."""
from pathlib import Path
import ast
import importlib.util

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("i18n_default_fa", root / "app/i18n.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
assert mod.DEFAULT_LANGUAGE == "fa"
for unknown in (None, "", "xx", "xx-XX"):
    assert mod.normalize_language(unknown) == "fa"
    assert mod.menu(unknown) == mod.MENU_LABELS["fa"]
assert mod.normalize_language("en") == "en"
assert mod.normalize_language("de") == "de"

source = (root / "app/main.py").read_text(encoding="utf-8")
ast.parse(source)
# Initial conversation MUST NOT infer the customer's interface language from
# their Telegram device locale. Do not reset any saved manual language selection.
assert 'user_languages[str(chat_id)] = DEFAULT_LANGUAGE' in source
assert 'str(from_user.get("language_code")' not in source
assert 'if str(chat_id) not in user_languages:' in source
assert 'default=DEFAULT_LANGUAGE' in source
assert 'default_profile = i18n_profile(DEFAULT_LANGUAGE)' in source
assert 'requested = parts[1] if len(parts) > 1 else DEFAULT_LANGUAGE' in source
assert 'await set_user_language(chat_id, requested)' in source
print("PERSIAN_BOT_DEFAULT_TEST_PASS")
