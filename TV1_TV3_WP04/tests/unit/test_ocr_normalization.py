from __future__ import annotations

import unicodedata

from aic2026.ocr import (
    character_ngrams,
    normalize_search_text,
    normalize_unicode_nfc,
    punctuation_aware_text,
    strip_vietnamese_diacritics,
)


def test_vietnamese_normalization_preserves_and_removes_diacritics():
    decomposed = unicodedata.normalize("NFD", "Cộng hòa Việt Nam")
    assert normalize_unicode_nfc(decomposed) == "Cộng hòa Việt Nam"
    assert normalize_search_text(decomposed) == "cộng hòa việt nam"
    assert normalize_search_text(strip_vietnamese_diacritics(decomposed)) == "cong hoa viet nam"
    assert strip_vietnamese_diacritics("Đường phố") == "Duong pho"


def test_punctuation_aware_normalization_keeps_symbols_as_tokens():
    assert punctuation_aware_text("AIC-2026: Việt Nam!") == "aic - 2026 : việt nam !"


def test_character_ngrams_are_deterministic_and_bounded():
    first = character_ngrams("Việt Nam", 2, 4, 12)
    second = character_ngrams("Việt Nam", 2, 4, 12)
    assert first == second
    assert len(first) == 12
    assert len(first) == len(set(first))
    assert first[0] == "vi"
