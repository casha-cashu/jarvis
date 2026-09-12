from __future__ import annotations

from unittest.mock import MagicMock
import pytest
import requests

from jarvis.modules.llm import (
    OpenRouterClient,
    is_rate_limit_error,
    parse_retry_after,
    with_rate_limit_retry,
)


class TestParseRetryAfter:
    def test_parse_numeric_seconds(self):
        assert parse_retry_after("5") == 5.0
        assert parse_retry_after("12.5") == 12.5
        assert parse_retry_after("  3  ") == 3.0

    def test_parse_empty_or_invalid(self):
        assert parse_retry_after(None, default_delay=2.0) == 2.0
        assert parse_retry_after("", default_delay=3.0) == 3.0
        assert parse_retry_after("not-a-date-or-number", default_delay=1.5) == 1.5

    def test_parse_http_date(self, monkeypatch):
        import email.utils
        from datetime import datetime, timezone

        # Future date: 10 seconds from now
        future_dt = datetime(2026, 9, 12, 12, 0, 10, tzinfo=timezone.utc)
        header = email.utils.format_datetime(future_dt)

        # Mock current time in email parsing context
        class MockDateTime:
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)

        monkeypatch.setattr("jarvis.modules.llm.datetime", MockDateTime)
        diff = parse_retry_after(header)
        assert abs(diff - 10.0) < 0.1

    def test_negative_clamped_to_zero(self):
        assert parse_retry_after("-5") == 0.0


class TestIsRateLimitError:
    def test_requests_429_with_header(self):
        resp = requests.Response()
        resp.status_code = 429
        resp.headers["Retry-After"] = "7"
        err = requests.HTTPError(response=resp)

        is_rl, retry_after = is_rate_limit_error(err)
        assert is_rl is True
        assert retry_after == 7.0

    def test_requests_non_429(self):
        resp = requests.Response()
        resp.status_code = 500
        err = requests.HTTPError(response=resp)

        is_rl, retry_after = is_rate_limit_error(err)
        assert is_rl is False
        assert retry_after is None

    def test_anthropic_rate_limit_error(self):
        import anthropic

        raw_resp = requests.Response()
        raw_resp.status_code = 429
        raw_resp.headers["retry-after"] = "4"

        # Construct Anthropic RateLimitError
        err = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=raw_resp,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        is_rl, retry_after = is_rate_limit_error(err)
        assert is_rl is True
        assert retry_after == 4.0

    def test_generic_exception(self):
        is_rl, retry_after = is_rate_limit_error(ValueError("boom"))
        assert is_rl is False
        assert retry_after is None


class TestWithRateLimitRetry:
    def test_success_on_first_try(self):
        mock_sleep = MagicMock()
        mock_op = MagicMock(return_value="ok")

        res = with_rate_limit_retry(
            mock_op, max_retries=3, base_delay=1.0, sleeper=mock_sleep
        )
        assert res == "ok"
        assert mock_op.call_count == 1
        assert mock_sleep.call_count == 0

    def test_retry_on_429_and_succeed(self):
        resp = requests.Response()
        resp.status_code = 429
        resp.headers["Retry-After"] = "2"
        err_429 = requests.HTTPError(response=resp)

        mock_op = MagicMock(side_effect=[err_429, err_429, "recovered"])
        mock_sleep = MagicMock()

        res = with_rate_limit_retry(
            mock_op, max_retries=3, base_delay=1.0, sleeper=mock_sleep
        )
        assert res == "recovered"
        assert mock_op.call_count == 3
        assert mock_sleep.call_count == 2
        # Both slept for the header value (2.0s)
        assert mock_sleep.call_args_list[0][0][0] == 2.0
        assert mock_sleep.call_args_list[1][0][0] == 2.0

    def test_exponential_backoff_without_header(self):
        resp = requests.Response()
        resp.status_code = 429
        err_429 = requests.HTTPError(response=resp)

        mock_op = MagicMock(side_effect=[err_429, "ok"])
        mock_sleep = MagicMock()

        res = with_rate_limit_retry(
            mock_op,
            max_retries=3,
            base_delay=1.0,
            max_delay=10.0,
            sleeper=mock_sleep,
            jitter=False,
        )
        assert res == "ok"
        assert mock_op.call_count == 2
        assert mock_sleep.call_count == 1
        # attempt 0 base delay 1.0 * (2^0) = 1.0
        assert mock_sleep.call_args_list[0][0][0] == 1.0

    def test_exceed_max_retries_raises(self):
        resp = requests.Response()
        resp.status_code = 429
        err_429 = requests.HTTPError(response=resp)

        mock_op = MagicMock(side_effect=err_429)
        mock_sleep = MagicMock()

        with pytest.raises(requests.HTTPError):
            with_rate_limit_retry(
                mock_op, max_retries=2, base_delay=0.1, sleeper=mock_sleep
            )

        # initial try + 2 retries = 3 calls
        assert mock_op.call_count == 3
        assert mock_sleep.call_count == 2

    def test_does_not_retry_non_429_errors(self):
        resp = requests.Response()
        resp.status_code = 401
        err_401 = requests.HTTPError(response=resp)

        mock_op = MagicMock(side_effect=err_401)
        mock_sleep = MagicMock()

        with pytest.raises(requests.HTTPError):
            with_rate_limit_retry(
                mock_op, max_retries=3, base_delay=0.1, sleeper=mock_sleep
            )

        assert mock_op.call_count == 1
        assert mock_sleep.call_count == 0


class TestClientRateLimitIntegration:
    def test_openrouter_retries_on_429(self, monkeypatch):
        cfg = {"openrouter": {"api_key": "fake-key", "model": "test-model"}}
        client = OpenRouterClient(cfg)

        resp_429 = requests.Response()
        resp_429.status_code = 429
        resp_429.headers["Retry-After"] = "1"

        resp_200 = requests.Response()
        resp_200.status_code = 200
        resp_200._content = b'{"choices":[{"message":{"content":"Hello after 429"}}]}'

        mock_post = MagicMock(side_effect=[resp_429, resp_200])
        monkeypatch.setattr("jarvis.modules.llm._http_post", mock_post)

        sleep_calls = []
        monkeypatch.setattr(
            "jarvis.modules.llm.time.sleep", lambda s: sleep_calls.append(s)
        )

        ans = client.chat("hi")
        assert ans == "Hello after 429"
        assert mock_post.call_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 1.0

    def test_openai_retries_on_429(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from jarvis.modules.llm import OpenAIClient

        client = OpenAIClient({"openai": {"model": "gpt-4o-mini"}})

        # Create simulated 429 error
        raw_resp = requests.Response()
        raw_resp.status_code = 429
        raw_resp.headers["retry-after"] = "3"
        err_429 = requests.HTTPError(response=raw_resp)

        success_resp = MagicMock()
        success_resp.choices = [MagicMock(message=MagicMock(content="Hello OpenAI"))]

        mock_create = MagicMock(side_effect=[err_429, success_resp])
        client.client = MagicMock()
        client.client.chat.completions.create = mock_create

        sleep_calls = []
        monkeypatch.setattr(
            "jarvis.modules.llm.time.sleep", lambda s: sleep_calls.append(s)
        )

        ans = client.chat("hello")
        assert ans == "Hello OpenAI"
        assert mock_create.call_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 3.0

    def test_anthropic_retries_on_429(self, monkeypatch):
        import anthropic

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from jarvis.modules.llm import AnthropicClient

        client = AnthropicClient({"anthropic": {"model": "claude-sonnet-4-20250514"}})

        raw_resp = requests.Response()
        raw_resp.status_code = 429
        raw_resp.headers["retry-after"] = "2.5"
        err_429 = anthropic.RateLimitError(
            message="Rate limit", response=raw_resp, body=None
        )

        success_resp = MagicMock()
        success_block = MagicMock()
        success_block.type = "text"
        success_block.text = "Hello Anthropic"
        success_resp.content = [success_block]

        mock_create = MagicMock(side_effect=[err_429, success_resp])
        client.client = MagicMock()
        client.client.messages.create = mock_create

        sleep_calls = []
        monkeypatch.setattr(
            "jarvis.modules.llm.time.sleep", lambda s: sleep_calls.append(s)
        )

        ans = client.chat("hello")
        assert ans == "Hello Anthropic"
        assert mock_create.call_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 2.5

    def test_ollama_retries_on_429(self, monkeypatch):
        from jarvis.modules.llm import OllamaClient

        client = OllamaClient({"ollama": {"base_url": "http://localhost:11434"}})

        resp_429 = requests.Response()
        resp_429.status_code = 429
        resp_429.headers["Retry-After"] = "1.5"

        resp_200 = requests.Response()
        resp_200.status_code = 200
        resp_200._content = b'{"message":{"content":"Hello Ollama"}}'

        mock_post = MagicMock(side_effect=[resp_429, resp_200])
        monkeypatch.setattr("jarvis.modules.llm._http_post", mock_post)

        sleep_calls = []
        monkeypatch.setattr(
            "jarvis.modules.llm.time.sleep", lambda s: sleep_calls.append(s)
        )

        ans = client.chat("hello")
        assert ans == "Hello Ollama"
        assert mock_post.call_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 1.5
