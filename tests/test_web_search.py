import json
from unittest.mock import MagicMock, patch

from jarvis.modules.web_search import (
    _HTMLTextExtractor,
    fetch_webpage,
    format_search_results,
    search_web,
    validate_public_http_url,
)


def test_html_text_extractor():
    extractor = _HTMLTextExtractor()
    html_content = """
    <html>
        <head><title>Ignore</title><script>alert(1);</script><style>.a{color:red;}</style></head>
        <body>
            <nav><a href="#">Menu</a></nav>
            <h1>Заголовок страницы</h1>
            <p>Первый абзац с информацией.</p>
            <div>Второй блок текста.</div>
        </body>
    </html>
    """
    extractor.feed(html_content)
    text = extractor.get_text()
    assert "Заголовок страницы" in text
    assert "Первый абзац с информацией" in text
    assert "Второй блок текста" in text
    assert "alert" not in text
    assert ".a{color:red;}" not in text
    assert "Menu" not in text


def test_format_search_results():
    results = [
        {"title": "Test 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
        {"title": "Test 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
    ]
    formatted = format_search_results(results)
    assert "1. **Test 1**" in formatted
    assert "https://example.com/1" in formatted
    assert "Snippet 2" in formatted

    assert format_search_results([]) == "Ничего не найдено по данному запросу."


def test_search_web_duckduckgo_mock():
    mock_html = """
    <div class="result__body">
        <a class="result__a" href="https://example.com/page">Example Title</a>
        <div class="result__snippet">Sample snippet description</div>
    </div>
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = mock_html.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = search_web("python programming")
        assert len(res) == 1
        assert res[0]["title"] == "Example Title"
        assert res[0]["url"] == "https://example.com/page"
        assert res[0]["snippet"] == "Sample snippet description"


def test_fetch_webpage_invalid_url():
    assert "Ошибка: некорректный URL" in fetch_webpage("ftp://invalid.url")


def test_search_web_brave_null_web_field():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"web": null}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = search_web("query", provider="brave", api_key="fake-key")
        assert res == []


def test_search_web_brave_http_error(caplog):
    import urllib.error

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.search.brave.com",
            code=429,
            msg="Rate Limited",
            hdrs={},
            fp=None,
        )

        res = search_web("query", provider="brave", api_key="fake-key")
        assert res == []
        assert "429" in caplog.text


def test_search_web_clean_html_and_control_chars():
    payload_obj = {
        "web": {
            "results": [
                {
                    "title": "<b>Python &amp; AI</b>\r\n\x07Heading",
                    "url": "https://example.com/py",
                    "description": "Learn <i>Python</i> &gt; 3.10!\x00\x1fEnjoy.",
                }
            ]
        }
    }
    mock_payload = json.dumps(payload_obj).encode("utf-8")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = mock_payload
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = search_web("query", provider="brave", api_key="fake-key")
        assert len(res) == 1
        assert res[0]["title"] == "Python & AI Heading"
        assert res[0]["snippet"] == "Learn Python > 3.10! Enjoy."
        assert "\r" not in res[0]["title"]
        assert "\n" not in res[0]["title"]
        assert "\x00" not in res[0]["snippet"]
        assert "<" not in res[0]["snippet"]


def test_search_web_response_buffer_limit():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"results": []}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        search_web("query", provider="tavily", api_key="fake-key")
        mock_response.read.assert_called_with(500_000)


def test_validate_public_http_url_blocks_loopback_and_private():
    # Loopback
    ok, reason = validate_public_http_url("http://127.0.0.1:8080/secret")
    assert not ok and "локальн" in reason or "приватн" in reason or not ok

    ok, reason = validate_public_http_url("http://localhost:3000/")
    assert not ok

    ok, reason = validate_public_http_url("http://[::1]:8080/")
    assert not ok

    # Cloud metadata (link-local)
    ok, reason = validate_public_http_url("http://169.254.169.254/latest/meta-data/")
    assert not ok

    # Private networks
    for private_url in [
        "http://10.0.0.1/admin",
        "http://192.168.1.1/",
        "http://172.16.0.1/status",
        "http://127.0.0.53/",
    ]:
        ok, reason = validate_public_http_url(private_url)
        assert not ok, f"Expected {private_url} to be blocked"


def test_validate_public_http_url_blocks_invalid_schemes_and_hosts():
    for bad_url in [
        "file:///etc/passwd",
        "gopher://127.0.0.1/",
        "ftp://example.com/test",
        "http:///no-host",
        "https://my-local-device.local/",
    ]:
        ok, reason = validate_public_http_url(bad_url)
        assert not ok, f"Expected {bad_url} to be blocked"


def test_validate_public_http_url_allows_public_ip():
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock public IP 93.184.216.34 (example.com)
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        ok, reason = validate_public_http_url("https://example.com/docs")
        assert ok
        assert reason == ""


def test_fetch_webpage_ssrf_guard_blocks_private():
    # Direct fetch to private targets should return [BLOCKED]
    res = fetch_webpage("http://127.0.0.1:8080/metrics")
    assert res.startswith("[BLOCKED]")
    assert "безопасности" in res or "локальн" in res or "127.0.0.1" in res

    res = fetch_webpage("http://169.254.169.254/latest/meta-data/")
    assert res.startswith("[BLOCKED]")


def test_fetch_webpage_blocks_redirect_to_private():
    # Mock redirect to 127.0.0.1
    import urllib.error

    with patch("socket.getaddrinfo") as mock_dns:
        # Initial public DNS ok
        mock_dns.side_effect = lambda host, *args, **kwargs: (
            [(2, 1, 6, "", ("127.0.0.1", 80))]
            if host == "127.0.0.1"
            else [(2, 1, 6, "", ("93.184.216.34", 443))]
        )

        with patch("jarvis.modules.web_search._SAFE_OPENER.open") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="http://127.0.0.1/admin",
                code=403,
                msg="[BLOCKED] SSRF protection: redirect to forbidden target",
                hdrs={},
                fp=None,
            )
            res = fetch_webpage("https://example.com/redirect")
            assert res.startswith("[BLOCKED]")
