"""
PrescpHealth Backend — Property Test: Translation Fallback (Property 15).

Validates that the i18n translation lookup ALWAYS returns a human-readable
string and NEVER returns the raw key. Missing translations fall back to
English ('en') before any other behaviour.

Invariants tested:
    1. If key exists in requested locale → return that locale's translation.
    2. If key missing in locale but exists in 'en' → return English translation.
    3. Result is NEVER equal to the raw key string itself.

No service import needed — the fallback function is defined locally because
the full i18n module is not yet implemented.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Standalone translation fallback implementation (to be moved to app.core.i18n)
# ---------------------------------------------------------------------------

# Simulated translation catalogue — locale → key → human-readable string
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "patient.risk_score_label": "Risk Score",
        "patient.name_label": "Full Name",
        "alert.critical": "Critical Alert",
        "common.save": "Save",
        "common.cancel": "Cancel",
    },
    "fr": {
        "patient.risk_score_label": "Score de Risque",
        "alert.critical": "Alerte Critique",
        "common.save": "Enregistrer",
    },
    "pt": {
        "patient.risk_score_label": "Pontuação de Risco",
        "common.cancel": "Cancelar",
    },
    "sw": {
        "alert.critical": "Tahadhari Muhimu",
    },
}


def translate(key: str, locale: str) -> str:
    """
    Look up a translation key in the given locale with English fallback.

    Args:
        key: Dot-notation translation key (e.g., "patient.risk_score_label").
        locale: BCP-47 language code (e.g., "fr", "sw").

    Returns:
        Human-readable translated string. Falls back to English if the key
        is missing in the requested locale. Returns a descriptive placeholder
        if the key is missing from English as well — NEVER the raw key.
    """
    # Try requested locale first
    locale_dict = _TRANSLATIONS.get(locale, {})
    if key in locale_dict:
        return locale_dict[key]

    # Fallback to English
    en_dict = _TRANSLATIONS.get("en", {})
    if key in en_dict:
        return en_dict[key]

    # Ultimate fallback: human-readable placeholder, NOT the raw key
    return "[Missing translation]"


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_KNOWN_KEYS = list(_TRANSLATIONS["en"].keys())

# Mix of known and arbitrary keys to test both paths
translation_keys = st.one_of(
    st.sampled_from(_KNOWN_KEYS),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P")),
        min_size=3, max_size=40,
    ),
)

# Mix of supported locales, unsupported locales, and arbitrary strings
locale_codes = st.one_of(
    st.sampled_from(["en", "fr", "pt", "sw", "ar"]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=5),
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestTranslationFallback:
    """Property tests for translation fallback behaviour."""

    @given(key=translation_keys, locale=locale_codes)
    @settings(max_examples=200)
    def test_property_result_never_equals_raw_key(self, key: str, locale: str):
        """Result must NEVER be the raw key string — always human-readable."""
        result = translate(key, locale)
        assert result != key, (
            f"translate({key!r}, {locale!r}) returned the raw key"
        )

    @given(locale=locale_codes)
    @settings(max_examples=100)
    def test_property_known_key_always_resolves(self, locale: str):
        """Keys that exist in English always resolve to a non-empty string."""
        for key in _KNOWN_KEYS:
            result = translate(key, locale)
            assert result, f"Empty result for known key {key!r} in locale {locale!r}"
            assert result != key

    @given(
        locale=st.sampled_from(["fr", "pt", "sw"]),
        data=st.data(),
    )
    @settings(max_examples=200)
    def test_property_locale_hit_preferred_over_english(self, locale: str, data):
        """If a key exists in the requested locale, that value is returned."""
        locale_dict = _TRANSLATIONS.get(locale, {})
        assume(len(locale_dict) > 0)
        key = data.draw(st.sampled_from(list(locale_dict.keys())))

        result = translate(key, locale)
        assert result == locale_dict[key], (
            f"Expected locale value {locale_dict[key]!r}, got {result!r}"
        )

    @given(key=st.sampled_from(_KNOWN_KEYS), locale=locale_codes)
    @settings(max_examples=150)
    def test_property_english_fallback_when_locale_missing(self, key: str, locale: str):
        """If key missing in locale, English value returned (not raw key)."""
        locale_dict = _TRANSLATIONS.get(locale, {})
        assume(key not in locale_dict)

        result = translate(key, locale)
        expected_en = _TRANSLATIONS["en"][key]
        assert result == expected_en, (
            f"Expected English fallback {expected_en!r}, got {result!r}"
        )
