def test_is_newer():
    from jarvis.cli import _is_newer

    assert _is_newer("v2.8.0", "2.7.0") is True
    assert _is_newer("2.7.0", "2.7.0") is False
    assert _is_newer("v2.6.2", "2.7.0") is False
    assert _is_newer("v2.10.0", "2.9.0") is True  # числовое, не строковое
    assert _is_newer("мусор", "2.7.0") is False
