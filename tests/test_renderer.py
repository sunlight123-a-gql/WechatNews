import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.article_writer import GeneratedArticle
from src.fetchers import NewsItem
from src.renderer import render_articles_html, render_articles_markdown, render_html, render_markdown


class RendererTests(unittest.TestCase):
    def test_render_html_escapes_content_and_links_sources(self):
        item = NewsItem(
            title="AI <Game> update",
            url="https://example.com/news",
            source="Source & Co",
            published_at=dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.timezone.utc),
            summary="A <short> summary & context.",
        )

        html = render_html([item], title="Daily <Digest>", intro="AI & games")

        self.assertIn("Daily &lt;Digest&gt;", html)
        self.assertIn("AI &lt;Game&gt; update", html)
        self.assertIn("Source &amp; Co", html)
        self.assertIn('href="https://example.com/news"', html)
        self.assertIn('style="color:#0969da;text-decoration:underline;"', html)
        self.assertIn(">点击阅读原文</a>", html)
        self.assertNotIn("<short>", html)

    def test_render_markdown_includes_empty_state(self):
        markdown = render_markdown([], title="Daily Digest", intro="No copied articles.")

        self.assertIn("# Daily Digest", markdown)
        self.assertIn("本次没有找到匹配的新闻", markdown)

    def test_render_markdown_uses_chinese_digest_style(self):
        item = NewsItem(
            title="OpenAI launches new AI tooling for game developers",
            url="https://example.com/news",
            source="AI Wire",
            published_at=dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.timezone.utc),
            summary="OpenAI released tools for game studios to improve production workflows.",
            category="ai",
        )

        markdown = render_markdown([item], title="AI/游戏行业日报", intro="今日重点")

        self.assertIn("# AI/游戏行业日报", markdown)
        self.assertIn("## 1. OpenAI launches new AI tooling for game developers", markdown)
        self.assertIn("这条消息来自 AI Wire", markdown)
        self.assertIn("从标题和摘要看", markdown)
        self.assertIn("原文链接：[点击阅读原文](https://example.com/news)", markdown)
        self.assertNotIn("- Source:", markdown)
        self.assertNotIn("- Summary:", markdown)

    def test_render_html_uses_chinese_digest_style(self):
        item = NewsItem(
            title="Unity announces AI workflow update",
            url="https://example.com/unity",
            source="Unity Blog",
            published_at=dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.timezone.utc),
            summary="Unity shared an update about AI-assisted game production.",
            category="game",
        )

        output = render_html([item], title="AI/游戏行业日报", intro="今日重点")

        self.assertIn("这条消息来自 Unity Blog", output)
        self.assertIn("从标题和摘要看", output)
        self.assertIn("原文链接", output)
        self.assertIn(">点击阅读原文</a>", output)

    def test_render_html_describes_public_affairs_category(self):
        item = NewsItem(
            title="公安机关部署专项行动",
            url="https://example.com/security",
            source="法治新闻",
            published_at=dt.datetime(2026, 8, 4, 1, 0, tzinfo=dt.timezone.utc),
            summary="行动聚焦公共安全和社会治理。",
            category="public_security",
        )

        output = render_html([item], title="热点新闻", intro="今日重点")

        self.assertIn("公安法治、公共安全或社会治理", output)

    def test_render_articles_markdown_outputs_long_article_shape(self):
        article = GeneratedArticle(
            title="AI 工具链正在改变游戏制作",
            body="AI 工具进入游戏制作流程，真正值得关注的不是工具本身，而是它正在改变团队分工和产业速度。",
            url="https://example.com/story",
            image_url="https://cdn.example.com/story.jpg",
        )

        markdown = render_articles_markdown([article], title="AI/游戏行业观察", intro="今日观察")

        self.assertIn("# AI/游戏行业观察", markdown)
        self.assertIn("## 1. AI 工具链正在改变游戏制作", markdown)
        self.assertIn("![AI 工具链正在改变游戏制作](https://cdn.example.com/story.jpg)", markdown)
        self.assertIn("AI 工具进入游戏制作流程", markdown)
        self.assertNotIn("原文链接", markdown)
        self.assertNotIn("点击阅读原文", markdown)
        self.assertNotIn("发布时间", markdown)
        self.assertNotIn("来源", markdown)

    def test_render_articles_html_outputs_article_body_and_link(self):
        article = GeneratedArticle(
            title="AI 工具链正在改变游戏制作",
            body="AI 工具进入游戏制作流程，真正值得关注的不是工具本身。",
            url="https://example.com/story",
            image_url="https://cdn.example.com/story.jpg",
        )

        output = render_articles_html([article], title="AI/游戏行业观察", intro="今日观察")

        self.assertIn("AI 工具链正在改变游戏制作", output)
        self.assertIn('font-size:22px;font-weight:700;', output)
        self.assertIn('<img src="https://cdn.example.com/story.jpg"', output)
        self.assertIn('alt="AI 工具链正在改变游戏制作"', output)
        self.assertIn("AI 工具进入游戏制作流程", output)
        self.assertNotIn('href="https://example.com/story"', output)
        self.assertNotIn("点击阅读原文", output)
        self.assertNotIn("原文链接", output)
        self.assertNotIn("发布时间", output)

    def test_render_articles_skips_image_when_source_has_none(self):
        article = GeneratedArticle(
            title="AI 工具链正在改变游戏制作",
            body="AI 工具进入游戏制作流程。",
            url="https://example.com/story",
            image_url=None,
        )

        output = render_articles_html([article], title="AI/游戏行业观察", intro="今日观察")
        markdown = render_articles_markdown([article], title="AI/游戏行业观察", intro="今日观察")

        self.assertNotIn("<img", output)
        self.assertNotIn("![", markdown)


if __name__ == "__main__":
    unittest.main()
