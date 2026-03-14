from bot.i18n import TRANSLATIONS, gettext


def test_refine_keys_present():
    # Direct dict check bypasses gettext's zh-tw fallback, which would mask missing "en" keys
    refine_keys = (
        "action_refine_existing",
        "action_refine",
        "action_refine_save",
        "action_refine_more",
        "refining",
        "refine_enter",
    )
    for lang in ("en", "zh-tw"):
        for key in refine_keys:
            assert key in TRANSLATIONS[lang], f"Missing key '{key}' for lang '{lang}'"


def test_refine_enter_format():
    result = gettext("en", "refine_enter", prompt="test prompt")
    assert "test prompt" in result
    result_tw = gettext("zh-tw", "refine_enter", prompt="測試 prompt")
    assert "測試 prompt" in result_tw
