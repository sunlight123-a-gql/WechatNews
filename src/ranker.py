from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetchers import NewsItem


TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"spm", "fbclid", "gclid", "yclid"}


@dataclass(frozen=True)
class ScoredItem:
    item: NewsItem
    score: int


def select_top_items(
    items: list[NewsItem],
    keywords: list[str],
    exclude_keywords: list[str],
    max_items: int,
    lookback_hours: int,
    now: dt.datetime | None = None,
    published_today_only: bool = False,
    timezone: dt.tzinfo = dt.timezone.utc,
    minimum_items: int = 0,
    fallback_categories: list[str] | None = None,
    fallback_keywords: list[str] | None = None,
    category_minimums: dict[str, int] | None = None,
    category_maximums: dict[str, int] | None = None,
) -> list[NewsItem]:
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=lookback_hours)
    local_today = now.astimezone(timezone).date()
    seen: set[str] = set()
    eligible: list[NewsItem] = []

    for item in items:
        if item.published_at is not None and item.published_at < cutoff:
            continue
        if published_today_only and not _is_published_on_date(item, local_today, timezone):
            continue

        haystack = f"{item.title} {item.summary} {item.source}".casefold()
        if _contains_any(haystack, exclude_keywords):
            continue
        eligible.append(item)

    scored: list[ScoredItem] = []
    for item in eligible:
        score = score_item(item, keywords)
        if score <= 0:
            continue

        fingerprint = _fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        scored.append(ScoredItem(item=item, score=score))

    scored.sort(
        key=lambda entry: (
            entry.score,
            entry.item.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        ),
        reverse=True,
    )
    selected = _select_with_category_minimums(
        [entry.item for entry in scored],
        max_items,
        category_minimums,
        category_maximums,
    )

    target_count = min(max_items, max(0, minimum_items))
    if len(selected) >= target_count:
        return selected

    fallback_category_set = {category.casefold() for category in fallback_categories or [] if category}
    if not fallback_category_set:
        return selected

    fallback_scored: list[ScoredItem] = []
    for item in eligible:
        if item.category.casefold() not in fallback_category_set:
            continue

        fingerprint = _fingerprint(item)
        if fingerprint in seen:
            continue

        fallback_score = score_item(item, fallback_keywords or [])
        if fallback_score <= 0:
            continue

        seen.add(fingerprint)
        fallback_scored.append(ScoredItem(item=item, score=fallback_score))

    fallback_scored.sort(
        key=lambda entry: (
            entry.item.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            entry.score,
        ),
        reverse=True,
    )
    selected = _select_with_category_minimums(
        [*selected, *(entry.item for entry in fallback_scored)],
        max_items,
        category_minimums,
        category_maximums,
    )
    if len(selected) > target_count:
        return selected[:target_count]
    return selected


def _is_published_on_date(item: NewsItem, local_date: dt.date, timezone: dt.tzinfo) -> bool:
    if item.published_at is None:
        return False
    return item.published_at.astimezone(timezone).date() == local_date


def score_item(item: NewsItem, keywords: list[str]) -> int:
    title = item.title.casefold()
    summary = item.summary.casefold()
    score = 0

    for keyword in keywords:
        if not keyword.strip():
            continue
        if _matches_keyword(title, keyword):
            score += 3
        if _matches_keyword(summary, keyword):
            score += 1

    return score


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith(TRACKING_PREFIXES)
        and key.casefold() not in TRACKING_PARAMS
    ]
    normalized_query = urlencode(query, doseq=True)
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            normalized_query,
            "",
        )
    )


def _fingerprint(item: NewsItem) -> str:
    normalized_title = re.sub(r"\W+", "", item.title.casefold())
    return normalize_url(item.url) or normalized_title


def _deduplicate_by_event(items: list[NewsItem], max_items: int) -> list[NewsItem]:
    if max_items <= 0:
        return []

    selected: list[NewsItem] = []
    seen_fingerprints: set[str] = set()
    seen_terms: list[tuple[set[str], set[str]]] = []

    for item in items:
        fingerprint = _fingerprint(item)
        if fingerprint in seen_fingerprints:
            continue

        title_terms = _title_terms(item)
        event_terms = _event_terms(item)
        if event_terms and any(
            _is_same_event(title_terms, event_terms, previous_title_terms, previous_event_terms)
            for previous_title_terms, previous_event_terms in seen_terms
        ):
            continue

        seen_fingerprints.add(fingerprint)
        if event_terms:
            seen_terms.append((title_terms, event_terms))
        selected.append(item)
        if len(selected) >= max_items:
            break

    return selected


def _select_with_category_minimums(
    items: list[NewsItem],
    max_items: int,
    category_minimums: dict[str, int] | None,
    category_maximums: dict[str, int] | None,
) -> list[NewsItem]:
    candidates = _deduplicate_by_event(items, len(items))
    if max_items <= 0:
        return []
    if not category_minimums and not category_maximums:
        return candidates[:max_items]

    normalized_maximums = {
        category.casefold().strip(): max(0, int(maximum))
        for category, maximum in (category_maximums or {}).items()
        if category.strip()
    }
    selected_fingerprints: set[str] = set()
    selected_counts: dict[str, int] = {}
    for category, minimum in (category_minimums or {}).items():
        normalized_category = category.casefold().strip()
        remaining = max(0, int(minimum))
        if not normalized_category or remaining == 0:
            continue

        for item in candidates:
            if len(selected_fingerprints) >= max_items or remaining == 0:
                break
            fingerprint = _fingerprint(item)
            if fingerprint in selected_fingerprints:
                continue
            if item.category.casefold() != normalized_category:
                continue
            maximum = normalized_maximums.get(normalized_category)
            if maximum is not None and selected_counts.get(normalized_category, 0) >= maximum:
                break
            selected_fingerprints.add(fingerprint)
            selected_counts[normalized_category] = selected_counts.get(normalized_category, 0) + 1
            remaining -= 1

    for item in candidates:
        if len(selected_fingerprints) >= max_items:
            break
        fingerprint = _fingerprint(item)
        if fingerprint in selected_fingerprints:
            continue
        category = item.category.casefold()
        maximum = normalized_maximums.get(category)
        if maximum is not None and selected_counts.get(category, 0) >= maximum:
            continue
        selected_fingerprints.add(fingerprint)
        selected_counts[category] = selected_counts.get(category, 0) + 1

    return [item for item in candidates if _fingerprint(item) in selected_fingerprints][:max_items]


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return any(_matches_keyword(haystack, needle) for needle in needles if needle)


def _matches_keyword(text: str, keyword: str) -> bool:
    needle = keyword.casefold().strip()
    if not needle:
        return False
    if _needs_word_boundaries(needle):
        pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in needle.split()) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return needle in text


def _needs_word_boundaries(value: str) -> bool:
    return all(char.isascii() and (char.isalnum() or char.isspace()) for char in value)


def _title_terms(item: NewsItem) -> set[str]:
    return _significant_terms(item.title)


def _event_terms(item: NewsItem) -> set[str]:
    return _significant_terms(f"{item.title} {item.summary}")


def _significant_terms(text: str) -> set[str]:
    normalized = text.casefold()
    latin_terms = {
        term
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(term := _normalize_event_token(token)) >= 4 and term not in _EVENT_STOPWORDS
    }
    chinese_terms = {
        chunk[index : index + 3]
        for chunk in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", normalized)
        for index in range(max(0, len(chunk) - 2))
    }
    return latin_terms | chinese_terms


def _normalize_event_token(token: str) -> str:
    if token in {"independence", "independent", "indie"}:
        return "independent"
    if token == "games":
        return "game"
    if token == "studios":
        return "studio"
    return token


def _is_same_event(
    current_title: set[str],
    current: set[str],
    previous_title: set[str],
    previous: set[str],
) -> bool:
    if _has_high_title_overlap(current_title, previous_title):
        return True

    overlap = current & previous
    if len(overlap) < 3:
        return False
    smaller_size = min(len(current), len(previous))
    return len(overlap) / smaller_size >= 0.45


def _has_high_title_overlap(current_title: set[str], previous_title: set[str]) -> bool:
    overlap = current_title & previous_title
    if len(overlap) < 5:
        return False
    smaller_size = min(len(current_title), len(previous_title))
    return smaller_size > 0 and len(overlap) / smaller_size >= 0.7


_EVENT_STOPWORDS = {
    "about",
    "after",
    "also",
    "from",
    "former",
    "formerly",
    "game",
    "going",
    "have",
    "into",
    "keep",
    "last",
    "latest",
    "more",
    "news",
    "over",
    "says",
    "some",
    "soon",
    "studio",
    "that",
    "their",
    "them",
    "these",
    "they",
    "this",
    "will",
    "with",
}
