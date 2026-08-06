from __future__ import annotations

import datetime as dt
import html

from .article_writer import GeneratedArticle
from .fetchers import NewsItem


def render_html(items: list[NewsItem], title: str, intro: str) -> str:
    today = dt.datetime.now().strftime("%Y-%m-%d")
    chunks = [
        '<section style="font-size:16px;line-height:1.75;color:#222;">',
        f"<h1>{html.escape(title)}</h1>",
        f'<p style="color:#57606a;">{html.escape(intro)}</p>',
        f'<p style="color:#8c8c8c;font-size:13px;">{today}</p>',
    ]

    if not items:
        chunks.append("<p>本次没有找到匹配的新闻。</p>")
    else:
        for index, item in enumerate(items, start=1):
            chunks.append(_render_html_item(index, item))

    chunks.append(
        '<p style="color:#8c8c8c;font-size:13px;">'
        "以上内容根据公开 RSS/Atom 源的标题和摘要整理，详细信息请阅读原文。"
        "</p>"
    )
    chunks.append("</section>")
    return "\n".join(chunks)


def render_markdown(items: list[NewsItem], title: str, intro: str) -> str:
    lines = [f"# {title}", "", intro, ""]

    if not items:
        lines.append("本次没有找到匹配的新闻。")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item.title}",
                "",
                _chinese_digest(item),
                "",
                _render_markdown_source_link(item.url),
                "",
            ]
        )

    return "\n".join(lines)


def render_articles_html(items: list[GeneratedArticle], title: str, intro: str) -> str:
    chunks = [
        '<section style="font-size:16px;line-height:1.8;color:#222;">',
        f"<h1>{html.escape(title)}</h1>",
        f'<p style="color:#57606a;">{html.escape(intro)}</p>',
    ]

    if not items:
        chunks.append("<p>本次没有生成文章。</p>")
    else:
        for index, item in enumerate(items, start=1):
            chunks.append(_render_article_html_item(index, item))

    chunks.append("</section>")
    return "\n".join(chunks)


def render_articles_markdown(items: list[GeneratedArticle], title: str, intro: str) -> str:
    lines = [f"# {title}", "", intro, ""]

    if not items:
        lines.append("本次没有生成文章。")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item.title}",
                "",
                *(_render_markdown_image(item) if item.image_url else []),
                item.body.strip(),
                "",
            ]
        )

    return "\n".join(lines)


def _render_html_item(index: int, item: NewsItem) -> str:
    return "\n".join(
        [
            '<section style="margin:20px 0;padding:14px 0;border-top:1px solid #eaecef;">',
            (
                '<h2 style="font-size:22px;font-weight:700;line-height:1.35;'
                'margin:28px 0 12px;color:#111;">'
                f"{index}. {html.escape(item.title)}</h2>"
            ),
            (
                '<p style="color:#57606a;font-size:14px;">'
                f"{html.escape(item.source)} · {html.escape(_format_date(item.published_at))}"
                "</p>"
            ),
            f"<p>{html.escape(_chinese_digest(item))}</p>",
            _render_html_source_link(item.url),
            "</section>",
        ]
    )


def _render_article_html_item(index: int, item: GeneratedArticle) -> str:
    paragraphs = [
        f"<p>{html.escape(paragraph.strip())}</p>"
        for paragraph in item.body.splitlines()
        if paragraph.strip()
    ]
    if not paragraphs:
        paragraphs = [f"<p>{html.escape(item.body.strip())}</p>"]

    return "\n".join(
        [
            '<section style="margin:26px 0;padding:18px 0;border-top:1px solid #eaecef;">',
            (
                '<h2 style="font-size:22px;font-weight:700;line-height:1.35;'
                'margin:28px 0 12px;color:#111;">'
                f"{index}. {html.escape(item.title)}</h2>"
            ),
            *(_render_article_image(item) if item.image_url else []),
            *paragraphs,
            "</section>",
        ]
    )


def _render_article_image(item: GeneratedArticle) -> list[str]:
    return [
        (
            f'<img src="{html.escape(item.image_url or "", quote=True)}" '
            f'alt="{html.escape(item.title, quote=True)}" '
            'style="width:100%;max-width:680px;height:auto;display:block;margin:12px 0 18px;" />'
        )
    ]


def _render_markdown_image(item: GeneratedArticle) -> list[str]:
    return [f"![{item.title}]({item.image_url})", ""]


def _render_html_source_link(url: str) -> str:
    escaped_url = html.escape(url, quote=True)
    return (
        '<p>原文链接：'
        f'<a href="{escaped_url}" style="color:#0969da;text-decoration:underline;">点击阅读原文</a>'
        "</p>"
    )


def _render_markdown_source_link(url: str) -> str:
    return f"原文链接：[点击阅读原文]({url})"


def _chinese_digest(item: NewsItem) -> str:
    summary = _shorten(item.summary, 180) if item.summary else "原始信息源没有提供摘要。"
    published = _format_date(item.published_at)
    topic_hint = _topic_hint(item)
    return (
        f"这条消息来自 {item.source}，发布时间为 {published}。"
        f"从标题和摘要看，重点是{topic_hint}。"
        f"原始摘要提到：{summary}"
    )


def _topic_hint(item: NewsItem) -> str:
    category_hints = {
        "public_security": "公安法治、公共安全或社会治理方面的新动态",
        "politics": "重要政策、政务部署或民生改革方面的新进展",
        "finance": "财政政策、宏观经济或金融监管方面的新变化",
        "technology": "科技创新、数字经济或产业升级方面的新进展",
    }
    category_hint = category_hints.get(item.category.casefold())
    if category_hint:
        return category_hint

    text = f"{item.title} {item.summary}".casefold()
    if any(
        keyword in text
        for keyword in ("openai", "google", "microsoft", "anthropic", "nvidia", "model", "ai")
    ):
        return "AI 技术、产品或产业合作的新进展"
    if any(
        keyword in text
        for keyword in ("game", "gaming", "playstation", "xbox", "unity", "unreal", "studio")
    ):
        return "游戏行业的业务变化、工具更新或市场动态"
    return "相关行业动态及其后续影响"


def _format_date(value: dt.datetime | None) -> str:
    if value is None:
        return "未知时间"
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."
