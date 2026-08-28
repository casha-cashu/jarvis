"""Тесты jarvis.resources — резолв упакованных ресурсов (data/*.json)."""

import sys
from pathlib import Path

from jarvis.resources import resource_path


class TestResourcePath:
    def test_prefers_existing_cwd_path(self, tmp_path, monkeypatch):
        """Dev-режим: путь от CWD существует — возвращается (резолвнутым)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "x.json").write_text("{}", encoding="utf-8")
        got = Path(resource_path("data/x.json")).resolve()
        assert got == (tmp_path / "data" / "x.json").resolve()

    def test_falls_back_to_meipass(self, tmp_path, monkeypatch):
        """PyInstaller onefile: ресурс лежит в sys._MEIPASS."""
        monkeypatch.chdir(tmp_path)  # в CWD ресурса нет
        meipass = tmp_path / "_MEI123"
        (meipass / "data").mkdir(parents=True)
        (meipass / "data" / "x.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        assert resource_path("data/x.json") == str(meipass / "data" / "x.json")

    def test_returns_original_when_missing(self, tmp_path, monkeypatch):
        """Ничего не найдено — исходный относительный путь (для честного
        лога «файл не найден» в вызывающем коде)."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        assert resource_path("data/nope.json") == "data/nope.json"

    def test_real_repo_data_resolves(self):
        """Санити: в репозитории словари резолвятся из CWD=корень."""
        import os
        from pathlib import Path

        if (Path.cwd() / "data" / "commands.json").exists():
            assert resource_path("data/commands.json").endswith("commands.json")
        else:
            # тест запущен не из корня — просто не должен упасть
            assert isinstance(resource_path("data/commands.json"), str)
            os.path.exists("data/commands.json")
