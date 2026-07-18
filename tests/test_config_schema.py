"""Тесты для jarvis.config_schema — pydantic валидация конфига.

config_schema претендует на то, что ловит ошибки пользователя в config.yaml
рано (до того как упадёт STT/TTS при init). Эти тесты фиксируют контракты,
которые должны держать валидаторы: разрешённые значения, defaults, типы.
Если кто-то добавит новое поле или поменяет default — тест покажет.
"""

import pytest
from pydantic import ValidationError

from jarvis.config_schema import (
    JarvisConfig,
    STTConfig,
    TTSConfig,
    LLMConfig,
    LoggingConfig,
)


class TestSTTConfig:
    def test_engine_valid_vosk(self):
        c = STTConfig(engine="vosk")
        assert c.engine == "vosk"

    def test_engine_valid_whisper(self):
        c = STTConfig(engine="whisper")
        assert c.engine == "whisper"

    def test_engine_invalid_raises(self):
        """Бессмысленное значение engine → внятная ошибка."""
        with pytest.raises(ValidationError) as exc:
            STTConfig(engine="macaque")
        assert "must be one of" in str(exc.value)

    def test_wake_mode_valid(self):
        assert STTConfig(wake_mode="classic").wake_mode == "classic"
        assert STTConfig(wake_mode="vad").wake_mode == "vad"

    def test_wake_mode_invalid_raises(self):
        with pytest.raises(ValidationError) as exc:
            STTConfig(wake_mode="passive")
        assert "wake_mode must be one of" in str(exc.value)

    def test_defaults_applied_on_empty(self):
        c = STTConfig()
        assert c.sample_rate == 16000
        assert c.wake_word == "джарвис"
        assert c.phrase_time_limit == 10
        assert c.pause_threshold == 1.2
        assert "jarvis" in c.wake_word_alternatives


class TestTTSConfig:
    def test_engine_valid(self):
        for engine in ("piper", "gtts", "speecht5"):
            assert TTSConfig(engine=engine).engine == engine

    def test_engine_invalid(self):
        with pytest.raises(ValidationError) as exc:
            TTSConfig(engine="eleven")
        assert "must be one of" in str(exc.value)

    def test_defaults(self):
        c = TTSConfig()
        assert c.engine == "piper"
        assert c.gtts.lang == "ru"
        assert c.speecht5.device == "cpu"


class TestLLMConfig:
    def test_provider_valid(self):
        for p in ("ollama", "kiro", "openrouter", "anthropic"):
            assert LLMConfig(provider=p).provider == p

    def test_provider_invalid(self):
        with pytest.raises(ValidationError) as exc:
            LLMConfig(provider="gemini")
        assert "must be one of" in str(exc.value)

    def test_max_history_default(self):
        assert LLMConfig().max_history == 20

    def test_ollama_has_url_default(self):
        c = LLMConfig()
        assert c.ollama.base_url == "http://localhost:11434"
        assert c.ollama.model == "qwen2.5:3b"

    def test_kiro_api_key_optional(self):
        # api_key может быть None — нет ключа → пустая подстановка в ConfigLoader
        c = LLMConfig()
        assert c.kiro.api_key is None


class TestLoggingConfig:
    def test_level_case_sensitive_uppercase_only(self):
        """level валидируется в верхнем регистре (INFO, info — fail)."""
        assert LoggingConfig(level="INFO").level == "INFO"
        assert LoggingConfig(level="DEBUG").level == "DEBUG"

    @pytest.mark.parametrize("level", ["info", "Info", "trace", "VERBOSE", ""])
    def test_level_invalid(self, level):
        with pytest.raises(ValidationError) as exc:
            LoggingConfig(level=level)
        assert "Log level must be one of" in str(exc.value)

    def test_defaults(self):
        c = LoggingConfig()
        assert c.file == "logs/jarvis.log"
        assert c.max_size == 10485760
        assert c.backup_count == 5
        assert c.log_recognized_text is True
        assert c.log_llm_requests is True


class TestJarvisConfigFull:
    """Полная схема: defaults пересчитаны, обязательные секции подставлены."""

    def test_empty_dict_uses_all_defaults(self):
        c = JarvisConfig()
        assert c.audio.microphone.sample_rate == 48000
        assert c.stt.engine == "vosk"
        assert c.tts.engine == "piper"
        assert c.llm.provider == "ollama"
        assert c.commands.execution_timeout == 30
        assert c.logging.level == "INFO"
        assert c.misc.temp_dir == "/tmp/jarvis"

    def test_partial_dict_merges_with_defaults(self):
        """Задали только audio.stt.engine — остальное должно подставиться."""
        c = JarvisConfig(stt={"engine": "whisper"})
        assert c.stt.engine == "whisper"
        assert c.stt.sample_rate == 16000  # default
        assert c.tts.engine == "piper"  # default

    def test_unknown_field_extra_allowed_by_default(self):
        """Pydantic v2 по умолчанию extra='ignore' для BaseModel —
        поля которых нет в схеме тихо выбрасываются. Проверим это,
        потому что файл config.yaml у пользователей может содержать
        старые/комментарные ключи (например «hyprland», который мы удалили).
        """
        c = JarvisConfig(hyprland={"enabled": False, "socket": "/tmp/x"})
        # hyprland секция удалена из схемы — она игнорируется
        assert not hasattr(c, "hyprland")

    def test_logging_level_propagates_error(self):
        """Неправильный logging.level ломает JarvisConfig."""
        with pytest.raises(ValidationError) as exc:
            JarvisConfig(logging={"level": "chatty"})
        assert "Log level" in str(exc.value)


class TestValidateConfig:
    """Контракт публичной API-функции validate_config()."""

    def test_returns_dict_not_model(self):
        """validate_config возвращает dict (model_dump), не pydantic model —
        остальной код ожидает dict (jarvis/__init__.py: self.config['stt']...).
        """
        from jarvis.config_schema import validate_config

        out = validate_config({})
        assert isinstance(out, dict)
        assert out["stt"]["engine"] == "vosk"

    def test_round_trip_preserves_values(self):
        """Значения заданные пользователем сохраняются в output."""
        from jarvis.config_schema import validate_config

        out = validate_config(
            {
                "stt": {"engine": "whisper", "pause_threshold": 2.0},
                "llm": {"provider": "anthropic", "max_history": 50},
            }
        )
        assert out["stt"]["engine"] == "whisper"
        assert out["stt"]["pause_threshold"] == 2.0
        assert out["llm"]["provider"] == "anthropic"
        assert out["llm"]["max_history"] == 50

    def test_invalid_raises_value_error_message(self):
        from jarvis.config_schema import validate_config

        with pytest.raises(ValidationError) as exc:
            validate_config({"tts": {"engine": "pikabu"}})
        assert "must be one of" in str(exc.value)


class TestNoDeadConfigKeys:
    """Контракт: dead config ключи (см. AGENTS.md «recent changes») не
    должны остаться в схеме. Если кто-то их вернёт — пусть это будет
    осознанное решение, тест скажет.
    """

    def test_misc_has_no_cleanup_temp_on_start(self):
        c = JarvisConfig()
        assert not hasattr(c.misc, "cleanup_temp_on_start")

    def test_misc_has_no_sound_notifications(self):
        c = JarvisConfig()
        assert not hasattr(c.misc, "sound_notifications")

    def test_misc_has_no_gui(self):
        c = JarvisConfig()
        assert not hasattr(c.misc, "gui")

    def test_jarvis_has_no_hyprland_attr(self):
        c = JarvisConfig()
        assert not hasattr(c, "hyprland")
