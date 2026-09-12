"""Web search and webpage reading module for JARVIS.

Supports:
- DuckDuckGo HTML search (free, no API key required)
- Brave Search API (optional, if key provided)
- Tavily Search API (optional, if key provided)
- Lightweight HTML-to-text webpage extraction
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _clean_text(text: str, is_title: bool = False) -> str:
    """Очищает сниппеты и заголовки от HTML-тегов, сущностей и управляющих символов."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = html.unescape(clean)
    if is_title:
        clean = re.sub(r"[\r\n\x00-\x1f]+", " ", clean)
    else:
        clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


class _HTMLTextExtractor(HTMLParser):
    """Clean text extractor from HTML, stripping script, style, nav, etc."""

    def __init__(self) -> None:
        super().__init__()
        self._ignore_tags = {
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "svg",
            "noscript",
            "iframe",
        }
        self._current_tag: list[str] = []
        self._pieces: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._current_tag.append(tag.lower())
        if tag.lower() in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self._current_tag and self._current_tag[-1] == tag_l:
            self._current_tag.pop()
        elif tag_l in self._current_tag:
            self._current_tag.remove(tag_l)
        if tag_l in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not any(t in self._ignore_tags for t in self._current_tag):
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class _DuckDuckGoHTMLParser(HTMLParser):
    """Parses results from https://html.duckduckgo.com/html/"""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._cur_title = ""
        self._cur_url = ""
        self._cur_snippet = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "").split()

        if "result" in classes or "result__body" in classes:
            self._in_result = True

        if "result__a" in classes:
            self._in_title = True
            href = attr_dict.get("href", "")
            # DuckDuckGo wraps URLs in /l/?uddg=...
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                uddg_vals = parsed.get("uddg")
                self._cur_url = uddg_vals[0] if uddg_vals else href
            else:
                self._cur_url = href

        if "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif self._in_snippet and tag in ("a", "td", "div", "span"):
            self._in_snippet = False
            if self._cur_title and self._cur_url:
                self.results.append(
                    {
                        "title": _clean_text(self._cur_title, is_title=True),
                        "url": self._cur_url.strip(),
                        "snippet": _clean_text(self._cur_snippet, is_title=False),
                    }
                )
                self._cur_title = ""
                self._cur_url = ""
                self._cur_snippet = ""
                self._in_result = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._cur_title += data
        elif self._in_snippet:
            self._cur_snippet += data


def duckduckgo_search(
    query: str, max_results: int = 5, timeout: int = 8
) -> list[dict[str, str]]:
    """Free web search via DuckDuckGo HTML endpoint without external deps."""
    url = "https://html.duckduckgo.com/html/"
    data = urllib.parse.urlencode({"q": query, "b": ""}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": _DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read(500_000).decode("utf-8", errors="replace")
        parser = _DuckDuckGoHTMLParser()
        parser.feed(content)
        return parser.results[:max_results]
    except urllib.error.HTTPError as e:
        logger.warning(f"DuckDuckGo search HTTP error {e.code}: {e.reason}")
        return []
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")
        return []


def brave_search(
    query: str, api_key: str, max_results: int = 5, timeout: int = 8
) -> list[dict[str, str]]:
    """Web search using Brave Search API."""
    params = urllib.parse.urlencode({"q": query, "count": max_results})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": _DEFAULT_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
            data = json.loads(raw)
        results = []
        web_data = data.get("web") or {}
        for item in (web_data.get("results") or [])[:max_results]:
            results.append(
                {
                    "title": _clean_text(item.get("title", ""), is_title=True),
                    "url": (item.get("url") or "").strip(),
                    "snippet": _clean_text(item.get("description", ""), is_title=False),
                }
            )
        return results
    except urllib.error.HTTPError as e:
        logger.warning(f"Brave search HTTP error {e.code}: {e.reason}")
        return []
    except Exception as e:
        logger.warning(f"Brave search failed: {e}")
        return []


def tavily_search(
    query: str, api_key: str, max_results: int = 5, timeout: int = 8
) -> list[dict[str, str]]:
    """Web search using Tavily Search API."""
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _DEFAULT_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
            data = json.loads(raw)
        results = []
        for item in (data.get("results") or [])[:max_results]:
            results.append(
                {
                    "title": _clean_text(item.get("title", ""), is_title=True),
                    "url": (item.get("url") or "").strip(),
                    "snippet": _clean_text(item.get("content", ""), is_title=False),
                }
            )
        return results
    except urllib.error.HTTPError as e:
        logger.warning(f"Tavily search HTTP error {e.code}: {e.reason}")
        return []
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return []


def search_web(
    query: str,
    provider: str = "duckduckgo",
    api_key: Optional[str] = None,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """Dispatches search to specified provider with fallback to DuckDuckGo."""
    if provider == "brave" and api_key:
        res = brave_search(query, api_key, max_results)
        if res:
            return res
    elif provider == "tavily" and api_key:
        res = tavily_search(query, api_key, max_results)
        if res:
            return res

    # Default / fallback to DuckDuckGo
    return duckduckgo_search(query, max_results)


def validate_public_http_url(url: str) -> tuple[bool, str]:
    """Validates that a URL points to a public, routable HTTP/HTTPS service.

    Blocks SSRF attacks targeting loopback, private RFC1918 subnets,
    link-local / cloud metadata (169.254.169.254), multicast, and reserved addresses.
    Returns (is_valid, error_reason).
    """
    if not url or not isinstance(url, str):
        return False, "URL не может быть пустым"

    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception as e:
        return False, f"Некорректный синтаксис URL: {e}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Недопустимая схема '{scheme}' (разрешены только http и https)"

    hostname = parsed.hostname
    if not hostname:
        return False, "Отсутствует имя хоста в URL"

    hostname_lower = hostname.lower().strip(".")
    if hostname_lower in ("localhost", "localhost.localdomain", "broadcasthost"):
        return False, f"Запрещён доступ к локальному хосту '{hostname}'"
    if hostname_lower.endswith((".local", ".localhost", ".internal", ".lan", ".home")):
        return False, f"Запрещён доступ к домену локальной сети '{hostname}'"

    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"Ошибка разрешения DNS для хоста '{hostname}': {e}"
    except Exception as e:
        return False, f"Не удалось разрешить адрес хоста '{hostname}': {e}"

    if not addr_info:
        return False, f"Не удалось получить IP-адреса для хоста '{hostname}'"

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Некорректный IP-адрес: {ip_str}"

        if ip.is_loopback:
            return False, f"Запрещён доступ к loopback адресу ({ip_str})"
        if ip.is_private:
            return False, f"Запрещён доступ к приватному IP-адресу ({ip_str})"
        if ip.is_link_local:
            return (
                False,
                f"Запрещён доступ к link-local / cloud metadata адресу ({ip_str})",
            )
        if ip.is_multicast:
            return False, f"Запрещён доступ к multicast адресу ({ip_str})"
        if ip.is_reserved:
            return False, f"Запрещён доступ к зарезервированному адресу ({ip_str})"
        if ip.is_unspecified:
            return False, f"Запрещён доступ к неопределённому адресу ({ip_str})"

    return True, ""


class _SSRFSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents HTTP redirects from escaping to private or local networks."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, reason = validate_public_http_url(newurl)
        if not ok:
            logger.warning(f"Blocked SSRF redirect to {newurl}: {reason}")
            raise urllib.error.HTTPError(
                newurl,
                403,
                f"[BLOCKED] SSRF protection: redirect to forbidden target ({reason})",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = urllib.request.build_opener(_SSRFSafeRedirectHandler())


def fetch_webpage(url: str, max_chars: int = 4000, timeout: int = 8) -> str:
    """Fetches a webpage and extracts clean, readable text content with SSRF protection."""
    if not (url and (url.startswith("http://") or url.startswith("https://"))):
        return "Ошибка: некорректный URL (должен начинаться с http:// или https://)"

    ok, reason = validate_public_http_url(url)
    if not ok:
        logger.warning(f"SSRF guard blocked fetch_webpage target '{url}': {reason}")
        return f"[BLOCKED] Запрос заблокирован политикой безопасности сети: {reason}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain",
        },
    )
    try:
        with _SAFE_OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read(500_000)  # limit download to 500 KB
            charset = resp.headers.get_content_charset() or "utf-8"
            html_text = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        if "[BLOCKED]" in str(e) or (e.reason and "[BLOCKED]" in str(e.reason)):
            return (
                f"[BLOCKED] Запрос заблокирован политикой безопасности сети: {e.reason}"
            )
        return f"Ошибка при загрузке страницы: {e}"
    except Exception as e:
        return f"Ошибка при загрузке страницы: {e}"

    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html_text)
        text = extractor.get_text()
        if len(text) > max_chars:
            text = (
                text[:max_chars]
                + f"\n\n[...содержимое усечено, показано первых {max_chars} символов]"
            )
        return text or "Пустая страница или не удалось извлечь текст."
    except Exception as e:
        return f"Ошибка при разборе страницы: {e}"


def format_search_results(results: list[dict[str, str]]) -> str:
    """Formats search results as clean markdown for LLM consumption."""
    if not results:
        return "Ничего не найдено по данному запросу."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**\n   URL: {r['url']}\n   {r['snippet']}")
    return "\n\n".join(lines)
