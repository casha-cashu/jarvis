#!/usr/bin/env python3
"""
LLM module for dialogue
Поддержка Kiro AI (Omniroute), OpenRouter, Anthropic, Ollama
"""

import os
import logging
from typing import Optional, List, Dict
import anthropic
import requests

logger = logging.getLogger(__name__)


class LLMClient:
    """Базовый класс для LLM клиентов"""

    def __init__(self, config: dict):
        self.config = config
        self.history: List[Dict[str, str]] = []
        self.max_history = config.get('max_history', 20)
        self.system_prompt = config.get('system_prompt', '')

    def add_to_history(self, role: str, content: str):
        """Добавляет сообщение в историю"""
        self.history.append({"role": role, "content": content})

        # Обрезаем историю если слишком длинная
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def clear_history(self):
        """Очищает историю"""
        self.history = []

    def chat(self, message: str) -> str:
        """Отправляет сообщение и получает ответ"""
        raise NotImplementedError


class KiroAIClient(LLMClient):
    """Клиент для Kiro AI (Omniroute) с Claude Sonnet 4.5"""

    def __init__(self, config: dict):
        super().__init__(config)

        kiro_config = config.get('kiro', {})
        self.api_key = os.getenv('KIRO_API_KEY') or kiro_config.get('api_key')
        self.base_url = kiro_config.get('base_url', 'https://api.kiroai.com/v1')
        self.model = kiro_config.get('model', 'claude-sonnet-4-5')
        self.temperature = kiro_config.get('temperature', 0.7)
        self.max_tokens = kiro_config.get('max_tokens', 1024)
        self.timeout = kiro_config.get('timeout', 30)

        if not self.api_key:
            raise ValueError("KIRO_API_KEY не установлен")

        logger.info(f"✅ Kiro AI клиент: {self.model}")

    def chat(self, message: str, stream_callback=None) -> str:
        """
        Отправляет сообщение в Kiro AI

        Args:
            message: Сообщение пользователя
            stream_callback: Функция для обработки streaming ответа (опционально)
        """
        try:
            self.add_to_history("user", message)

            # Формируем запрос
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": bool(stream_callback)  # Streaming если есть callback
            }

            # Отправляем запрос
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
                stream=bool(stream_callback)
            )

            response.raise_for_status()

            # Streaming режим
            if stream_callback:
                full_text = ""
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data = line[6:]
                            if data == '[DONE]':
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk['choices'][0]['delta'].get('content', '')
                                if delta:
                                    full_text += delta
                                    stream_callback(delta)
                            except:
                                continue

                self.add_to_history("assistant", full_text)
                return full_text

            # Обычный режим
            data = response.json()
            answer = data['choices'][0]['message']['content'].strip()
            self.add_to_history("assistant", answer)
            return answer

        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут Kiro AI")
            return "Извините, сэр, превышено время ожидания ответа."
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка Kiro AI: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            return "Извините, сэр, произошла системная ошибка."


class AnthropicClient(LLMClient):
    """Клиент для Anthropic API (прямой)"""

    def __init__(self, config: dict):
        super().__init__(config)

        anthropic_config = config.get('anthropic', {})
        api_key = os.getenv('ANTHROPIC_API_KEY') or anthropic_config.get('api_key')

        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY не установлен")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = anthropic_config.get('model', 'claude-3-5-sonnet-20241022')
        self.temperature = anthropic_config.get('temperature', 0.7)
        self.max_tokens = anthropic_config.get('max_tokens', 1024)

        logger.info(f"✅ Anthropic клиент: {self.model}")

    def chat(self, message: str) -> str:
        """Отправляет сообщение в Anthropic API"""
        try:
            self.add_to_history("user", message)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=self.history
            )

            answer = response.content[0].text.strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Anthropic: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."


class OpenRouterClient(LLMClient):
    """Клиент для OpenRouter"""

    def __init__(self, config: dict):
        super().__init__(config)

        openrouter_config = config.get('openrouter', {})
        self.api_key = os.getenv('OPENROUTER_API_KEY') or openrouter_config.get('api_key')
        self.model = openrouter_config.get('model', 'anthropic/claude-3.5-sonnet')
        self.temperature = openrouter_config.get('temperature', 0.7)

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не установлен")

        logger.info(f"✅ OpenRouter клиент: {self.model}")

    def chat(self, message: str) -> str:
        """Отправляет сообщение в OpenRouter"""
        try:
            self.add_to_history("user", message)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
            }

            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature
            }

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            answer = data['choices'][0]['message']['content'].strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка OpenRouter: {e}")
            return "Извините, сэр, произошла ошибка связи с ИИ."


class OllamaClient(LLMClient):
    """Клиент для локального Ollama"""

    def __init__(self, config: dict):
        super().__init__(config)

        ollama_config = config.get('ollama', {})
        self.base_url = ollama_config.get('base_url', 'http://localhost:11434')
        self.model = ollama_config.get('model', 'qwen2.5:3b')
        self.temperature = ollama_config.get('temperature', 0.7)

        logger.info(f"✅ Ollama клиент: {self.model}")

    def chat(self, message: str) -> str:
        """Отправляет сообщение в Ollama"""
        try:
            self.add_to_history("user", message)

            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})

            messages.extend(self.history)

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.temperature
                }
            }

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            answer = data['message']['content'].strip()
            self.add_to_history("assistant", answer)

            return answer

        except Exception as e:
            logger.error(f"❌ Ошибка Ollama: {e}")
            return "Извините, сэр, локальная модель недоступна."


class LLMManager:
    """Менеджер LLM с автоматическим fallback"""

    def __init__(self, config: dict):
        """
        Args:
            config: Словарь с настройками из config.yaml['llm']
        """
        self.config = config
        self.provider = config.get('provider', 'kiro')
        self.clients = {}

        # Инициализируем клиенты
        self._init_clients()

        # Выбираем основной
        self.primary = self.clients.get(self.provider)
        if not self.primary:
            logger.error(f"❌ Провайдер '{self.provider}' недоступен")
            # Берём первый доступный
            if self.clients:
                self.primary = list(self.clients.values())[0]
                logger.info(f"✅ Используется fallback: {list(self.clients.keys())[0]}")

    def _init_clients(self):
        """Инициализирует доступные клиенты"""
        # Kiro AI
        try:
            if self.config.get('kiro', {}).get('api_key') or os.getenv('KIRO_API_KEY'):
                self.clients['kiro'] = KiroAIClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ Kiro AI недоступен: {e}")

        # Anthropic
        try:
            if self.config.get('anthropic', {}).get('api_key') or os.getenv('ANTHROPIC_API_KEY'):
                self.clients['anthropic'] = AnthropicClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ Anthropic недоступен: {e}")

        # OpenRouter
        try:
            if self.config.get('openrouter', {}).get('api_key') or os.getenv('OPENROUTER_API_KEY'):
                self.clients['openrouter'] = OpenRouterClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ OpenRouter недоступен: {e}")

        # Ollama
        try:
            self.clients['ollama'] = OllamaClient(self.config)
        except Exception as e:
            logger.warning(f"⚠️ Ollama недоступен: {e}")

        if not self.clients:
            raise RuntimeError("❌ Ни один LLM провайдер не доступен")

    def chat(self, message: str, stream_callback=None) -> str:
        """
        Отправляет сообщение в LLM

        Args:
            message: Сообщение пользователя
            stream_callback: Функция для streaming (опционально)

        Returns:
            Ответ LLM
        """
        if not self.primary:
            return "Извините, сэр, ИИ недоступен."

        try:
            kwargs = {}
            if stream_callback is not None:
                kwargs['stream_callback'] = stream_callback
            return self.primary.chat(message, **kwargs)
        except Exception as e:
            logger.error(f"❌ Ошибка LLM: {e}")

            # Пробуем fallback (без streaming)
            for name, client in self.clients.items():
                if client != self.primary:
                    try:
                        logger.info(f"🔄 Пробую fallback: {name}")
                        return client.chat(message)
                    except:
                        continue

            return "Извините, сэр, все ИИ системы недоступны."

    def clear_history(self):
        """Очищает историю всех клиентов"""
        for client in self.clients.values():
            client.clear_history()
