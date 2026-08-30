#!/usr/bin/env python3
"""
Pydantic-модели для валидации конфигурации JARVIS.
"""

from typing import Optional
from pydantic import ConfigDict, BaseModel, Field, field_validator


class AudioMicrophoneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    device_name: Optional[str] = "default"
    sample_rate: int = 48000


class AudioOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    device_name: Optional[str] = None
    sample_rate: int = 48000


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    microphone: AudioMicrophoneConfig = Field(default_factory=AudioMicrophoneConfig)
    output: AudioOutputConfig = Field(default_factory=AudioOutputConfig)


class VoskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    model_path: str = "auto"


class WhisperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    model_path: Optional[str] = None
    model_size: str = "tiny"
    # Интервал промежуточных гипотез (мс); 0 = выключить
    partial_interval_ms: int = Field(default=1000, ge=0)


class STTConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    engine: str = "vosk"
    sample_rate: int = 16000
    vosk: VoskConfig = Field(default_factory=VoskConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    wake_word: str = "джарвис"
    wake_word_alternatives: list = ["жарвис", "джервис", "jarvis"]
    phrase_time_limit: int = 10
    multi_turn_timeout: int = 10
    wake_mode: str = "classic"
    # Секунд тишины для завершения фразы; None → дефолт движка
    # (vosk 2.0, whisper 1.0)
    silence_threshold: Optional[float] = None

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, v: str) -> str:
        allowed = ("vosk", "whisper")
        if v not in allowed:
            raise ValueError(f"STT engine must be one of {allowed}, got '{v}'")
        return v

    @field_validator("wake_mode")
    @classmethod
    def validate_wake_mode(cls, v: str) -> str:
        allowed = ("classic", "vad")
        if v not in allowed:
            raise ValueError(f"wake_mode must be one of {allowed}, got '{v}'")
        return v

    @field_validator("silence_threshold")
    @classmethod
    def validate_silence_threshold(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("silence_threshold must be a positive number of seconds")
        return v


class SileroVADConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    model_path: str = "auto"
    threshold: float = 0.5


class VADConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    enabled: bool = True
    engine: str = "silero"
    silero: SileroVADConfig = Field(default_factory=SileroVADConfig)


class PiperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    binary_path: Optional[str] = None
    model_path: Optional[str] = None
    config_path: Optional[str] = None
    lib_path: Optional[str] = None
    speaker_id: int = 0
    length_scale: float = 1.0


class GTTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    lang: str = "ru"
    slow: bool = False


class SpeechT5Config(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    model: Optional[str] = None
    vocoder_path: Optional[str] = None
    device: str = "cpu"
    speaker_id: int = 0


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    engine: str = "piper"
    piper: PiperConfig = Field(default_factory=PiperConfig)
    gtts: GTTSConfig = Field(default_factory=GTTSConfig)
    speecht5: SpeechT5Config = Field(default_factory=SpeechT5Config)

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, v: str) -> str:
        allowed = ("piper", "gtts", "speecht5")
        if v not in allowed:
            raise ValueError(f"TTS engine must be one of {allowed}, got '{v}'")
        return v


class OpenRouterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    api_key: Optional[str] = None
    model: str = "anthropic/claude-3.5-sonnet"
    temperature: float = 0.7
    timeout: int = 30


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    temperature: float = 0.7
    # 120с: локальная модель грузится с диска, не-стриминг /api/chat
    # молчит до конца генерации
    timeout: int = 120


class OpenAIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # None → api.openai.com
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: int = 30


class AnthropicConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )  # опечатка в ключе должна падать валидацией, а не молча игнорироваться
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # None → api.anthropic.com
    model: str = "claude-3-5-sonnet-20241022"
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: int = 30


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    provider: str = "ollama"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    # Agent loop options — see jarvis.response_pipeline
    agent_enabled: bool = False
    agent_max_iterations: int = 5
    agent_approval_mode: str = "auto"
    # Prefix nudge for small Ollama models (see jarvis.prompt_builder)
    agent_query_prefix_enabled: bool = False
    # Секция про инструменты, дописывается к system_prompt при agent_enabled
    # (compose_system_prompt в ResponsePipeline.start)
    system_prompt_tools: Optional[str] = None
    max_history: int = 20
    system_prompt: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = ("ollama", "openai", "openrouter", "anthropic")
        if v not in allowed:
            raise ValueError(f"LLM provider must be one of {allowed}, got '{v}'")
        return v

    @field_validator("agent_approval_mode")
    @classmethod
    def validate_approval_mode(cls, v: str) -> str:
        allowed = ("auto", "strict", "yolo")
        if v not in allowed:
            raise ValueError(f"agent_approval_mode must be one of {allowed}, got '{v}'")
        return v


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    enabled: bool = False
    bot_token: Optional[str] = None  # или TELEGRAM_BOT_TOKEN в окружении
    allowed_chat_ids: list = []  # fail-closed: пусто = никто не допущен
    config_path: str = "config.yaml"  # путь конфига для бота


class CommandsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )  # опечатка в ключе должна падать валидацией, а не молча игнорироваться
    dictionary_path: str = "data/commands.json"
    apps_dictionary_path: str = "data/apps.json"
    fuzzy_threshold: float = 0.8
    execution_timeout: int = 30
    # NLU (jarvis.modules.nlu) — см. CommandManager._maybe_init_nlu
    nlu_enabled: bool = True
    nlu_confidence_threshold: float = 0.65


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    level: str = "INFO"
    file: str = "logs/jarvis.log"
    max_size: int = 10485760
    backup_count: int = 5

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = ("DEBUG", "INFO", "WARNING", "ERROR")
        if v not in allowed:
            raise ValueError(f"Log level must be one of {allowed}, got '{v}'")
        return v


class MiscConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации
    temp_dir: str = "/tmp/jarvis"


class JarvisConfig(BaseModel):
    """Полная схема конфигурации JARVIS"""

    model_config = ConfigDict(extra="forbid")  # опечатка в ключе = ошибка валидации

    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    vad: VADConfig = Field(default_factory=VADConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    misc: MiscConfig = Field(default_factory=MiscConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


def validate_config(config: dict) -> dict:
    """
    Валидирует словарь конфига через pydantic-модель.
    Возвращает dict с заполненными значениями (defaults для пропущенных полей).

    Raises:
        ValueError: если конфиг не проходит валидацию
    """
    validated = JarvisConfig(**config)
    return validated.model_dump()
