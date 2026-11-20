#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("beonmeet_i18n", ROOT / "app" / "i18n.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

langs = MODULE.SUPPORTED_LANGUAGES
assert tuple(langs) == ("fa", "en", "de")
assert set(MODULE.MESSAGES["fa"]) == set(MODULE.MESSAGES["en"]) == set(MODULE.MESSAGES["de"])
assert set(MODULE.MENU_LABELS["fa"]) == set(MODULE.MENU_LABELS["en"]) == set(MODULE.MENU_LABELS["de"])

for lang in langs:
    assert MODULE.normalize_language(lang) == lang
    assert MODULE.menu(lang)["language"]
    assert MODULE.profile(lang)["commands"]["language"]
    for key, template in MODULE.MESSAGES[lang].items():
        assert isinstance(template, str) and template.strip(), (lang, key)

assert MODULE.normalize_language("fa-IR") == "fa"
assert MODULE.normalize_language("de-DE") == "de"
assert MODULE.normalize_language("en-US") == "en"

# New and unknown locales default to Persian without overriding an explicit choice.
assert MODULE.DEFAULT_LANGUAGE == "fa"
assert MODULE.normalize_language(None) == "fa"
assert MODULE.normalize_language("") == "fa"
assert MODULE.normalize_language("fr-FR") == "fa"
assert MODULE.normalize_language("unknown", default="bogus") == "fa"
assert MODULE.normalize_language("en-US") == "en"
assert MODULE.normalize_language("de-DE") == "de"
assert MODULE.menu(None) == MODULE.MENU_LABELS["fa"]
assert MODULE.profile(None) == MODULE.PROFILE_TEXT["fa"]
assert MODULE.tr(None, "language_changed") == MODULE.MESSAGES["fa"]["language_changed"]
assert MODULE.BUTTON_ACTIONS["🇮🇷 فارسی"] == "/setlanguage fa"
assert MODULE.BUTTON_ACTIONS["🇬🇧 English"] == "/setlanguage en"
assert MODULE.BUTTON_ACTIONS["🇩🇪 Deutsch"] == "/setlanguage de"

print("I18N_TEST_PASS")
