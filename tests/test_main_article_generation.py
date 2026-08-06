import datetime as dt
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.article_writer import GeneratedArticle
from src.fetchers import NewsItem
from src.main import main


class MainArticleGenerationTests(unittest.TestCase):
    def test_main_sends_generated_digest_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yml"
            sources = root / "sources.yml"
            output = root / "output"
            config.write_text(
                textwrap.dedent(
                    """
                    title_template: "Public Affairs {date}"
                    intro: "Today"
                    max_items: 1
                    lookback_hours: 24
                    keywords:
                      - policy
                    exclude_keywords:
                    article_generation:
                      enabled: false
                    email:
                      enabled: false
                      subject_template: "Daily Email {date}"
                    wechat:
                      create_draft: false
                    """
                ).strip(),
                encoding="utf-8",
            )
            sources.write_text(
                textwrap.dedent(
                    """
                    sources:
                      - name: Example
                        url: https://example.com/feed.xml
                        category: politics
                        enabled: true
                    """
                ).strip(),
                encoding="utf-8",
            )
            item = NewsItem(
                title="Policy update",
                url="https://example.com/story",
                source="Example",
                published_at=None,
                summary="Public policy update.",
                category="politics",
            )

            with (
                patch("src.main.fetch_all_sources", return_value=[item]),
                patch("src.main.select_top_items", return_value=[item]),
                patch("src.main.send_html_email") as send_html_email,
            ):
                exit_code = main(
                    [
                        "--config",
                        str(config),
                        "--sources",
                        str(sources),
                        "--output",
                        str(output),
                        "--send-email",
                    ]
                )

            self.assertEqual(exit_code, 0)
            send_html_email.assert_called_once()
            self.assertIn("Policy update", send_html_email.call_args.args[0])
            self.assertTrue(send_html_email.call_args.kwargs["subject"].startswith("Daily Email "))

    def test_main_renders_generated_articles_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yml"
            sources = root / "sources.yml"
            output = root / "output"
            config.write_text(
                textwrap.dedent(
                    """
                    title_template: "AI/Game Industry Watch {date}"
                    intro: "Today"
                    max_items: 1
                    lookback_hours: 24
                    published_today_only: true
                    timezone: "Asia/Shanghai"
                    timeout_seconds: 5
                    keywords:
                      - AI
                    exclude_keywords:
                    article_generation:
                      enabled: true
                      api_key: "config-key"
                      model: "deepseek-chat"
                      max_articles: 1
                    wechat:
                      create_draft: false
                    """
                ).strip(),
                encoding="utf-8",
            )
            sources.write_text(
                textwrap.dedent(
                    """
                    sources:
                      - name: Example
                        url: https://example.com/feed.xml
                        category: ai
                        enabled: true
                    """
                ).strip(),
                encoding="utf-8",
            )
            item = NewsItem(
                title="AI changes game production",
                url="https://example.com/story",
                source="Example",
                published_at=None,
                summary="AI changes workflows.",
            )

            with (
                patch("src.main.fetch_all_sources", return_value=[item]),
                patch("src.main.select_top_items", return_value=[item]) as select_top_items,
                patch("src.main.DeepSeekArticleClient") as client_class,
                patch(
                    "src.main.generate_articles",
                    return_value=[
                        GeneratedArticle(
                            title=item.title,
                            body="Generated article body.",
                            url=item.url,
                            image_url="https://cdn.example.com/story.jpg",
                        )
                    ],
                ),
            ):
                exit_code = main(
                    [
                        "--config",
                        str(config),
                        "--sources",
                        str(sources),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(select_top_items.call_args.kwargs["published_today_only"])
            self.assertEqual(select_top_items.call_args.kwargs["timezone"], dt.timezone(dt.timedelta(hours=8)))
            client_class.assert_called_once()
            self.assertEqual(client_class.call_args.kwargs["api_key"], "config-key")
            html = next(output.glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("Generated article body.", html)
            self.assertIn('<img src="https://cdn.example.com/story.jpg"', html)
            self.assertFalse(list(output.glob("*.md")))

    def test_main_passes_minimum_and_fallback_config_to_selection_and_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yml"
            sources = root / "sources.yml"
            output = root / "output"
            config.write_text(
                textwrap.dedent(
                    """
                    title_template: "AI/Game Daily {date}"
                    intro: "Today"
                    max_items: 12
                    minimum_articles: 5
                    lookback_hours: 36
                    published_today_only: true
                    timezone: "Asia/Shanghai"
                    timeout_seconds: 5
                    keywords:
                      - AI
                      - game
                    fallback_categories:
                      - tech
                    fallback_keywords:
                      - technology
                      - software
                    category_minimums:
                      politics: 2
                      technology: 1
                    category_maximums:
                      politics: 5
                      technology: 4
                    exclude_keywords:
                    article_generation:
                      enabled: true
                      api_key: "config-key"
                      model: "deepseek-chat"
                      max_articles: 2
                    wechat:
                      create_draft: false
                    """
                ).strip(),
                encoding="utf-8",
            )
            sources.write_text(
                textwrap.dedent(
                    """
                    sources:
                      - name: Example
                        url: https://example.com/feed.xml
                        category: ai
                        enabled: true
                    """
                ).strip(),
                encoding="utf-8",
            )
            items = [
                NewsItem(
                    title=f"AI or technology story {index}",
                    url=f"https://example.com/story-{index}",
                    source="Example",
                    published_at=dt.datetime(2026, 7, 6, index, tzinfo=dt.timezone.utc),
                    summary="AI technology update.",
                )
                for index in range(5)
            ]

            with (
                patch("src.main.fetch_all_sources", return_value=items),
                patch("src.main.select_top_items", return_value=items) as select_top_items,
                patch("src.main.DeepSeekArticleClient"),
                patch("src.main.generate_articles", return_value=[]) as generate_articles,
            ):
                exit_code = main(
                    [
                        "--config",
                        str(config),
                        "--sources",
                        str(sources),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(select_top_items.call_args.kwargs["minimum_items"], 5)
            self.assertEqual(select_top_items.call_args.kwargs["fallback_categories"], ["tech"])
            self.assertEqual(select_top_items.call_args.kwargs["fallback_keywords"], ["technology", "software"])
            self.assertEqual(
                select_top_items.call_args.kwargs["category_minimums"],
                {"politics": 2, "technology": 1},
            )
            self.assertEqual(
                select_top_items.call_args.kwargs["category_maximums"],
                {"politics": 5, "technology": 4},
            )
            self.assertEqual(list(generate_articles.call_args.args[0]), items)

    def test_main_auto_publishes_created_draft_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.yml"
            sources = root / "sources.yml"
            output = root / "output"
            config.write_text(
                textwrap.dedent(
                    """
                    title_template: "AI/Game Daily {date}"
                    intro: "Today"
                    max_items: 1
                    lookback_hours: 24
                    timeout_seconds: 5
                    keywords:
                      - AI
                    exclude_keywords:
                    article_generation:
                      enabled: false
                    wechat:
                      create_draft: true
                      auto_publish: true
                      author: "Auto"
                      digest: "Daily digest."
                      source_url: ""
                    """
                ).strip(),
                encoding="utf-8",
            )
            sources.write_text(
                textwrap.dedent(
                    """
                    sources:
                      - name: Example
                        url: https://example.com/feed.xml
                        category: ai
                        enabled: true
                    """
                ).strip(),
                encoding="utf-8",
            )
            item = NewsItem(
                title="AI changes game production",
                url="https://example.com/story",
                source="Example",
                published_at=None,
                summary="AI changes workflows.",
            )

            with (
                patch("src.main.fetch_all_sources", return_value=[item]),
                patch("src.main.select_top_items", return_value=[item]),
                patch("src.main.credentials_from_env", return_value=object()),
                patch("src.main.get_access_token", return_value="token123"),
                patch.dict("os.environ", {"WECHAT_THUMB_MEDIA_ID": "thumb123"}, clear=False),
                patch("src.main.add_draft", return_value="draft-media-123") as add_draft,
                patch("src.main.submit_freepublish", return_value="publish123") as submit_freepublish,
            ):
                exit_code = main(
                    [
                        "--config",
                        str(config),
                        "--sources",
                        str(sources),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            add_draft.assert_called_once()
            submit_freepublish.assert_called_once_with("token123", "draft-media-123")


if __name__ == "__main__":
    unittest.main()
