from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable


LOGGER = logging.getLogger(__name__)
USER_AGENT = "wechat-news-publisher/1.0 (+https://github.com/)"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    category: str = "general"
    enabled: bool = True
    format: str = "feed"
    article_path_prefix: str = ""
    allow_subdomains: bool = False


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: dt.datetime | None
    summary: str = ""
    category: str = "general"


def fetch_all_sources(sources: Iterable[Source], timeout_seconds: int = 20) -> list[NewsItem]:
    items: list[NewsItem] = []
    for source in sources:
        if not source.enabled:
            continue

        try:
            items.extend(fetch_feed(source, timeout_seconds=timeout_seconds))
        except Exception as exc:  # noqa: BLE001 - keep one bad feed from breaking the digest.
            LOGGER.warning("Skipping source %s after fetch/parse failure: %s", source.name, exc)

    return items


def fetch_feed(source: Source, timeout_seconds: int = 20) -> list[NewsItem]:
    if source.format.casefold() == "html":
        return fetch_news_page(source, timeout_seconds=timeout_seconds)

    if source.url.startswith("gdelt://search"):
        request_url = _gdelt_request_url(source.url)
    else:
        request_url = source.url

    request = urllib.request.Request(request_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
    if source.url.startswith("gdelt://search"):
        return parse_gdelt_articles(data, source)
    return parse_feed(data, source)


def fetch_news_page(source: Source, timeout_seconds: int = 20) -> list[NewsItem]:
    request = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
        final_url = response.url
        charset = response.headers.get_content_charset() or "utf-8"

    try:
        page = data.decode(charset, errors="replace")
    except LookupError:
        page = data.decode("utf-8", errors="replace")

    parser = _NewsPageLinkParser()
    parser.feed(page)
    source_url = urllib.parse.urlsplit(final_url)
    source_path_prefix = source.article_path_prefix.strip().rstrip("/") or source_url.path.rstrip("/")
    if not source.article_path_prefix and "." in source_path_prefix.rsplit("/", maxsplit=1)[-1]:
        source_path_prefix = source_path_prefix.rsplit("/", maxsplit=1)[0] or "/"
    items: list[NewsItem] = []
    seen_urls: set[str] = set()

    for href, raw_title, date_hint in parser.links:
        article_url = urllib.parse.urljoin(final_url, href)
        article_parts = urllib.parse.urlsplit(article_url)
        if article_parts.scheme not in {"http", "https"}:
            continue
        source_host = (source_url.hostname or "").casefold()
        article_host = (article_parts.hostname or "").casefold()
        base_host = source_host.removeprefix("www.")
        same_site = article_host == source_host or (
            source.allow_subdomains
            and (article_host == base_host or article_host.endswith("." + base_host))
        )
        if not same_site:
            continue
        if source_path_prefix and source_path_prefix != "/" and not article_parts.path.startswith(
            source_path_prefix + "/"
        ):
            continue

        published_at = _published_at_from_url(article_url)
        if published_at is None and date_hint:
            published_at = _published_at_from_url(urllib.parse.urljoin(final_url, date_hint))
        title = _clean_space(html.unescape(raw_title))
        normalized_url = urllib.parse.urlunsplit(
            (article_parts.scheme, article_parts.netloc, article_parts.path, article_parts.query, "")
        )
        if published_at is None or len(title) < 4 or normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)
        items.append(
            NewsItem(
                title=title,
                url=normalized_url,
                source=source.name,
                published_at=published_at,
                category=source.category,
            )
        )

    return items


def parse_gdelt_articles(data: bytes, source: Source) -> list[NewsItem]:
    payload = json.loads(data.decode("utf-8", errors="replace"))
    items: list[NewsItem] = []
    for article in payload.get("articles", []):
        title = str(article.get("title", "")).strip()
        url = str(article.get("url", "")).strip()
        if not title or not url:
            continue

        domain = str(article.get("domain", "")).strip()
        image = str(article.get("socialimage", "")).strip()
        summary_parts = [part for part in [domain, image] if part]
        items.append(
            NewsItem(
                title=_clean_space(title),
                url=url,
                source=source.name,
                published_at=parse_gdelt_datetime(str(article.get("seendate", ""))),
                summary=" ".join(summary_parts),
                category=source.category,
            )
        )
    return items


def parse_feed(data: bytes, source: Source) -> list[NewsItem]:
    root = ET.fromstring(data)
    if root.tag.lower().endswith("rss") or root.find("channel") is not None:
        return _parse_rss(root, source)
    return _parse_atom(root, source)


def _parse_rss(root: ET.Element, source: Source) -> list[NewsItem]:
    items: list[NewsItem] = []
    channel = root.find("channel")
    if channel is None:
        return items

    for node in channel.findall("item"):
        title = _text(node, "title")
        link = _text(node, "link")
        if not title or not link:
            continue

        items.append(
            NewsItem(
                title=_clean_space(title),
                url=link.strip(),
                source=source.name,
                published_at=parse_datetime(_text(node, "pubDate") or _text(node, "date")),
                summary=_clean_summary(_text(node, "description") or _text(node, "summary")),
                category=source.category,
            )
        )
    return items


def _parse_atom(root: ET.Element, source: Source) -> list[NewsItem]:
    ns = _namespace(root.tag)
    entry_name = f"{{{ns}}}entry" if ns else "entry"
    items: list[NewsItem] = []

    for node in root.findall(entry_name):
        title = _text(node, "title", ns)
        link = _atom_link(node, ns)
        if not title or not link:
            continue

        items.append(
            NewsItem(
                title=_clean_space(title),
                url=link.strip(),
                source=source.name,
                published_at=parse_datetime(
                    _text(node, "published", ns) or _text(node, "updated", ns)
                ),
                summary=_clean_summary(_text(node, "summary", ns) or _text(node, "content", ns)),
                category=source.category,
            )
        )
    return items


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None

    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)

    try:
        normalized = value.strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def parse_gdelt_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return parse_datetime(value)


def _gdelt_request_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query = params.get("query", "").strip()
    max_records = params.get("max_records", "50").strip() or "50"
    gdelt_params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "maxrecords": max_records,
    }
    timespan = params.get("timespan", "1d").strip()
    if timespan:
        gdelt_params["timespan"] = timespan
    return "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(gdelt_params)


def _text(node: ET.Element, name: str, namespace: str | None = None) -> str:
    child_name = f"{{{namespace}}}{name}" if namespace else name
    child = node.find(child_name)
    if child is None or child.text is None:
        return ""
    return child.text


def _atom_link(node: ET.Element, namespace: str | None) -> str:
    link_name = f"{{{namespace}}}link" if namespace else "link"
    for link in node.findall(link_name):
        href = link.attrib.get("href", "")
        rel = link.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            return href
    first = node.find(link_name)
    return "" if first is None else first.attrib.get("href", "")


def _namespace(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


class _NewsPageLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str | None]] = []
        self._href: str | None = None
        self._anchor_depth = 0
        self._text_parts: list[str] = []
        self._date_hint: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.casefold(): value for name, value in attrs if value}
        if tag == "a":
            if self._href is None:
                self._href = attr_map.get("href")
                self._text_parts = []
                self._date_hint = None
            self._anchor_depth += 1
        elif tag == "img" and self._href:
            alt = attr_map.get("alt") or attr_map.get("title")
            if alt:
                self._text_parts.append(alt)
            if self._date_hint is None:
                self._date_hint = attr_map.get("src") or attr_map.get("data-src")

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._anchor_depth == 0:
            return
        self._anchor_depth -= 1
        if self._anchor_depth == 0:
            if self._href:
                self.links.append((self._href, " ".join(self._text_parts), self._date_hint))
            self._href = None
            self._text_parts = []
            self._date_hint = None

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)


def _published_at_from_url(url: str) -> dt.datetime | None:
    path = urllib.parse.urlsplit(url).path
    patterns = (
        r"/(?:n1/)?(20\d{2})/(\d{2})(\d{2})/",
        r"/(20\d{2})(\d{2})(\d{2})/",
        r"W0(20\d{2})(\d{2})(\d{2})",
        r"/(20\d{2})-(\d{2})/(\d{2})/",
        r"/(20\d{2})/(\d{2})/(\d{2})/",
    )
    for pattern in patterns:
        match = re.search(pattern, path)
        if match is None:
            continue
        try:
            local_time = dt.datetime(
                *(int(part) for part in match.groups()),
                tzinfo=dt.timezone(dt.timedelta(hours=8)),
            )
        except ValueError:
            return None
        return local_time.astimezone(dt.timezone.utc)
    return None


def _clean_space(value: str) -> str:
    return " ".join(value.split())


def _clean_summary(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return _clean_space(html.unescape(without_tags))
