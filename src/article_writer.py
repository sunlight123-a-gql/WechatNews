from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Iterable, Protocol

from .fetchers import NewsItem, USER_AGENT


LOGGER = logging.getLogger(__name__)
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class GeneratedArticle:
    title: str
    body: str
    url: str
    image_url: str | None = None


@dataclass(frozen=True)
class ArticleContent:
    text: str
    image_url: str | None = None


class ArticleClient(Protocol):
    def write_article(self, item: NewsItem, article_text: str) -> str:
        ...


def generate_articles(
    items: Iterable[NewsItem],
    client: ArticleClient,
    fetch_text: Callable[[str, int], str | ArticleContent] | None = None,
    timeout_seconds: int = 20,
) -> list[GeneratedArticle]:
    fetch_text = fetch_text or fetch_article_text
    articles: list[GeneratedArticle] = []

    for item in items:
        try:
            fetched = fetch_text(item.url, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - one blocked page should not stop the digest.
            LOGGER.warning("Falling back to feed summary for %s after article fetch failed: %s", item.url, exc)
            fetched = ArticleContent(text=item.summary)

        if isinstance(fetched, ArticleContent):
            article_text = fetched.text
            image_url = fetched.image_url
        else:
            article_text = fetched
            image_url = None

        body = client.write_article(item, article_text or item.summary)
        articles.append(GeneratedArticle(title=item.title, body=body.strip(), url=item.url, image_url=image_url))

    return articles


def fetch_article_text(url: str, timeout_seconds: int = 20) -> ArticleContent:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
    return extract_article_content(data, url)


def extract_article_text(data: bytes) -> str:
    return extract_article_content(data).text


def extract_article_content(data: bytes, base_url: str = "") -> ArticleContent:
    parser = _ReadableTextParser()
    parser.feed(data.decode("utf-8", errors="ignore"))
    image_url = parser.article_image_url or parser.meta_image_url
    if image_url and base_url:
        image_url = urllib.parse.urljoin(base_url, image_url)
    return ArticleContent(
        text=_clean_text(" ".join(parser.article_text or parser.body_text)),
        image_url=image_url,
    )


def build_article_prompt(item: NewsItem, article_text: str) -> str:
    source_text = _clean_text(article_text)
    if len(source_text) > 9000:
        source_text = source_text[:9000]

    return f"""
你是一名中文时政与公共事务新闻专栏作者。请根据下面的公开新闻内容，写一篇约500字的中文说明文或议论文。

写作要求：
1. 不要写来源、发布时间、作者、栏目名等流水账信息。
2. 不要逐句翻译原文，也不要保留英文摘要腔。
3. 先抓住核心事件，再解释它为什么重要，最后给出趋势判断或影响分析。
4. 文章应当有清晰观点，语言适合微信公众号读者。
5. 保持事实克制，不能编造原文没有的信息。
6. 不要写小标题，不要列项目符号，只输出正文。
7. 正文约500字，至少三段。

新闻标题：
{item.title}

RSS摘要：
{item.summary}

原文正文：
{source_text}
""".strip()


class DeepSeekArticleClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        api_url: str = DEEPSEEK_API_URL,
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.model = model
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for LLM article generation.")

    def write_article(self, item: NewsItem, article_text: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你只输出客观、克制的中文正文，不输出免责声明、标题、项目符号或原文链接。",
                },
                {"role": "user", "content": build_article_prompt(item, article_text)},
            ],
            "temperature": 0.4,
            "max_tokens": 1200,
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API error {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API request failed: {exc}") from exc

        parsed = json.loads(response_body)
        try:
            return str(parsed["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"DeepSeek API response did not include message content: {parsed}") from exc


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._article_depth = 0
        self.body_text: list[str] = []
        self.article_text: list[str] = []
        self.article_image_url: str | None = None
        self.meta_image_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside"}:
            self._ignored_depth += 1
        if tag == "article" or _has_article_class(attrs):
            self._article_depth += 1
        if tag == "meta":
            self._record_meta_image(attrs)
        if tag == "img" and self._article_depth and not self._ignored_depth and self.article_image_url is None:
            self.article_image_url = _image_src(attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if tag == "article" and self._article_depth:
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        self.body_text.append(text)
        if self._article_depth:
            self.article_text.append(text)

    def _record_meta_image(self, attrs: list[tuple[str, str | None]]) -> None:
        if self.meta_image_url is not None:
            return
        attr_map = {name.casefold(): value for name, value in attrs if value}
        property_name = (attr_map.get("property") or attr_map.get("name") or "").casefold()
        if property_name in {"og:image", "twitter:image"} and attr_map.get("content"):
            self.meta_image_url = attr_map["content"]


def _image_src(attrs: list[tuple[str, str | None]]) -> str | None:
    attr_map = {name.casefold(): value for name, value in attrs if value}
    for key in ("src", "data-src", "data-original"):
        value = attr_map.get(key)
        if value:
            return value
    srcset = attr_map.get("srcset")
    if srcset:
        return srcset.split(",", maxsplit=1)[0].strip().split()[0]
    return None


def _has_article_class(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if name in {"class", "id"} and value:
            lowered = value.casefold()
            if any(token in lowered for token in ("article", "post-content", "entry-content")):
                return True
    return False


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
