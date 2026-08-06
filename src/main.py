from __future__ import annotations

import argparse
import base64
import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.article_writer import DeepSeekArticleClient, generate_articles
from src.config_loader import load_yaml
from src.email_sender import send_html_email
from src.fetchers import Source, fetch_all_sources
from src.ranker import select_top_items
from src.renderer import render_articles_html, render_html
from src.wechat import (
    add_draft,
    build_draft_payload,
    credentials_from_env,
    get_access_token,
    submit_freepublish,
    upload_permanent_image,
)


LOGGER = logging.getLogger("wechat-news-publisher")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(levelname)s: %(message)s")

    config = load_yaml(Path(args.config))
    sources_config = load_yaml(Path(args.sources))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_objects = [
        Source(
            name=str(source["name"]),
            url=str(source["url"]),
            category=str(source.get("category", "general")),
            enabled=bool(source.get("enabled", True)),
            format=str(source.get("format", "feed")),
            article_path_prefix=str(source.get("article_path_prefix", "")),
            allow_subdomains=bool(source.get("allow_subdomains", False)),
        )
        for source in sources_config.get("sources", [])
    ]

    items = fetch_all_sources(source_objects, timeout_seconds=int(config.get("timeout_seconds", 20)))
    selected = select_top_items(
        items,
        keywords=list(config.get("keywords", [])),
        exclude_keywords=list(config.get("exclude_keywords", [])),
        max_items=int(config.get("max_items", 12)),
        lookback_hours=int(config.get("lookback_hours", 36)),
        published_today_only=bool(config.get("published_today_only", False)),
        timezone=parse_timezone(str(config.get("timezone", "+00:00"))),
        minimum_items=int(config.get("minimum_articles", 0)),
        fallback_categories=list(config.get("fallback_categories", [])),
        fallback_keywords=list(config.get("fallback_keywords", [])),
        category_minimums={
            str(category): int(minimum)
            for category, minimum in dict(config.get("category_minimums", {})).items()
        },
        category_maximums={
            str(category): int(maximum)
            for category, maximum in dict(config.get("category_maximums", {})).items()
        },
    )

    title = render_title(str(config.get("title_template", "Public Affairs Daily {date}")))
    intro = str(config.get("intro", "A concise daily digest of public-affairs news."))

    article_config = config.get("article_generation", {})
    if bool(article_config.get("enabled", False)):
        article_limit = max(
            int(article_config.get("max_articles", len(selected))),
            int(config.get("minimum_articles", 0)),
        )
        article_items = selected[:article_limit]
        client = DeepSeekArticleClient(
            api_key=str(article_config.get("api_key", "")) or None,
            model=str(article_config.get("model", "deepseek-chat")),
            timeout_seconds=int(article_config.get("llm_timeout_seconds", 60)),
        )
        articles = generate_articles(
            article_items,
            client=client,
            timeout_seconds=int(article_config.get("article_timeout_seconds", config.get("timeout_seconds", 20))),
        )
        html = render_articles_html(articles, title=title, intro=intro)
    else:
        html = render_html(selected, title=title, intro=intro)

    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    html_path = output_dir / f"{stamp}.html"
    html_path.write_text(html, encoding="utf-8")
    LOGGER.info("Wrote %s", html_path)

    email_config = config.get("email", {})
    send_email = args.send_email or bool(email_config.get("enabled", False))
    if send_email:
        if args.dry_run:
            LOGGER.info("Email sending skipped in dry-run mode.")
        else:
            email_subject = render_title(
                str(email_config.get("subject_template", "Public Affairs Daily {date}"))
            )
            send_html_email(html, subject=email_subject)
            LOGGER.info("Sent email digest.")

    if args.dry_run or not bool(config.get("wechat", {}).get("create_draft", False)):
        LOGGER.info("Draft creation skipped.")
        return 0

    create_wechat_draft(config, html)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a daily public-affairs news digest from public feeds.")
    parser.add_argument("--config", default="config.yml")
    parser.add_argument("--sources", default="sources.yml")
    parser.add_argument("--output", default="output")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate local artifacts without sending email or calling WeChat.",
    )
    parser.add_argument("--send-email", action="store_true", help="Send the generated HTML digest by SMTP.")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def render_title(template: str) -> str:
    today = dt.datetime.now().strftime("%Y-%m-%d")
    return template.format(date=today)


def parse_timezone(value: str) -> dt.tzinfo:
    normalized = value.strip()
    if normalized in {"Asia/Shanghai", "China", "CST", "+08:00", "+0800"}:
        return dt.timezone(dt.timedelta(hours=8))
    if normalized in {"UTC", "Z", "+00:00", "+0000"}:
        return dt.timezone.utc

    sign = 1
    if normalized.startswith("-"):
        sign = -1
        normalized = normalized[1:]
    elif normalized.startswith("+"):
        normalized = normalized[1:]

    if ":" in normalized:
        hour_text, minute_text = normalized.split(":", maxsplit=1)
    else:
        hour_text, minute_text = normalized[:2], normalized[2:] or "0"

    return dt.timezone(sign * dt.timedelta(hours=int(hour_text), minutes=int(minute_text)))


def create_wechat_draft(config: dict[str, Any], html: str) -> str:
    wechat_config = config.get("wechat", {})
    credentials = credentials_from_env()
    access_token = get_access_token(credentials)
    thumb_media_id = os.getenv("WECHAT_THUMB_MEDIA_ID", "").strip()

    if not thumb_media_id:
        cover_path = Path(str(wechat_config.get("cover_image", "assets/default-cover.png")))
        if not cover_path.exists():
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            cover_path.write_bytes(base64.b64decode(DEFAULT_COVER_PNG_BASE64))
        thumb_media_id = upload_permanent_image(access_token, cover_path)

    title = render_title(str(config.get("title_template", "Public Affairs Daily {date}")))
    payload = build_draft_payload(
        title=title,
        author=str(wechat_config.get("author", "Auto")),
        digest=str(wechat_config.get("digest", "Daily public-affairs news digest.")),
        html=html,
        thumb_media_id=thumb_media_id,
        source_url=str(wechat_config.get("source_url", "")),
    )
    media_id = add_draft(access_token, payload)
    LOGGER.info("Created WeChat draft media_id=%s", media_id)
    if bool(wechat_config.get("auto_publish", False)):
        publish_id = submit_freepublish(access_token, media_id)
        LOGGER.info("Submitted WeChat publish publish_id=%s", publish_id)
    return media_id


DEFAULT_COVER_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGOSHzRgAAAAABJRU5ErkJggg=="
)


if __name__ == "__main__":
    raise SystemExit(main())
