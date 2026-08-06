import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fetchers import NewsItem
from src.ranker import select_top_items


class RankerTests(unittest.TestCase):
    def test_select_top_items_filters_scores_and_deduplicates(self):
        now = dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.timezone.utc)
        items = [
            NewsItem(
                title="OpenAI releases new game AI agent",
                url="https://example.com/story?utm_source=feed",
                source="AI Wire",
                published_at=now,
                summary="OpenAI and Unity game workflows.",
            ),
            NewsItem(
                title="OpenAI releases new game AI agent",
                url="https://example.com/story",
                source="Mirror",
                published_at=now - dt.timedelta(hours=1),
                summary="Duplicate story.",
            ),
            NewsItem(
                title="Cooking tools update",
                url="https://example.com/cooking",
                source="Other",
                published_at=now,
                summary="No matching terms.",
            ),
            NewsItem(
                title="Tencent game studio launches AI NPC tooling",
                url="https://example.com/tencent-ai-npc",
                source="Game Biz",
                published_at=now - dt.timedelta(minutes=30),
                summary="Game production news.",
            ),
        ]

        selected = select_top_items(
            items,
            keywords=["AI", "OpenAI", "game", "Unity", "Tencent"],
            exclude_keywords=["cooking"],
            max_items=5,
            lookback_hours=24,
            now=now,
        )

        self.assertEqual([item.title for item in selected], [
            "OpenAI releases new game AI agent",
            "Tencent game studio launches AI NPC tooling",
        ])

    def test_select_top_items_ignores_stale_items(self):
        now = dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.timezone.utc)
        old_item = NewsItem(
            title="AI game update",
            url="https://example.com/old",
            source="Archive",
            published_at=now - dt.timedelta(days=3),
            summary="Old but relevant.",
        )

        selected = select_top_items(
            [old_item],
            keywords=["AI", "game"],
            exclude_keywords=[],
            max_items=5,
            lookback_hours=24,
            now=now,
        )

        self.assertEqual(selected, [])

    def test_select_top_items_can_require_same_beijing_calendar_day(self):
        now = dt.datetime(2026, 7, 4, 2, 0, tzinfo=dt.timezone.utc)  # 2026-07-04 10:00 Asia/Shanghai
        today_item = NewsItem(
            title="AI game update today",
            url="https://example.com/today",
            source="AI Wire",
            published_at=dt.datetime(2026, 7, 3, 16, 1, tzinfo=dt.timezone.utc),
            summary="AI game production news.",
        )
        yesterday_item = NewsItem(
            title="AI game update yesterday",
            url="https://example.com/yesterday",
            source="AI Wire",
            published_at=dt.datetime(2026, 7, 3, 15, 59, tzinfo=dt.timezone.utc),
            summary="AI game production news.",
        )
        undated_item = NewsItem(
            title="AI game update without date",
            url="https://example.com/undated",
            source="AI Wire",
            published_at=None,
            summary="AI game production news.",
        )

        selected = select_top_items(
            [today_item, yesterday_item, undated_item],
            keywords=["AI", "game"],
            exclude_keywords=[],
            max_items=5,
            lookback_hours=36,
            now=now,
            published_today_only=True,
            timezone=dt.timezone(dt.timedelta(hours=8)),
        )

        self.assertEqual(selected, [today_item])

    def test_select_top_items_fills_minimum_with_today_tech_fallback(self):
        now = dt.datetime(2026, 7, 6, 2, 0, tzinfo=dt.timezone.utc)  # 2026-07-06 10:00 Asia/Shanghai
        primary_ai = NewsItem(
            title="AI model changes game production",
            url="https://example.com/ai-game",
            source="AI Wire",
            published_at=dt.datetime(2026, 7, 6, 0, 30, tzinfo=dt.timezone.utc),
            summary="AI game workflows.",
            category="ai",
        )
        primary_game = NewsItem(
            title="Unity game tooling update",
            url="https://example.com/unity-game",
            source="Game Wire",
            published_at=dt.datetime(2026, 7, 5, 18, 0, tzinfo=dt.timezone.utc),
            summary="Game production news.",
            category="game",
        )
        tech_items = [
            NewsItem(
                title="Apple device launch adds new technology platform",
                url="https://example.com/apple-device",
                source="Tech Wire",
                published_at=dt.datetime(2026, 7, 6, 1, 0, tzinfo=dt.timezone.utc),
                summary="Consumer technology update.",
                category="tech",
            ),
            NewsItem(
                title="Cloud software startup raises new funding",
                url="https://example.com/cloud-startup",
                source="Tech Wire",
                published_at=dt.datetime(2026, 7, 5, 20, 0, tzinfo=dt.timezone.utc),
                summary="Software and cloud infrastructure.",
                category="tech",
            ),
            NewsItem(
                title="Chip company expands semiconductor production",
                url="https://example.com/chip-company",
                source="Tech Wire",
                published_at=dt.datetime(2026, 7, 5, 16, 5, tzinfo=dt.timezone.utc),
                summary="Semiconductor technology.",
                category="tech",
            ),
            NewsItem(
                title="Yesterday technology platform update",
                url="https://example.com/yesterday-tech",
                source="Tech Wire",
                published_at=dt.datetime(2026, 7, 5, 15, 59, tzinfo=dt.timezone.utc),
                summary="Technology news.",
                category="tech",
            ),
        ]

        selected = select_top_items(
            [primary_ai, primary_game, *tech_items],
            keywords=["AI", "game", "Unity"],
            exclude_keywords=[],
            max_items=12,
            lookback_hours=36,
            now=now,
            published_today_only=True,
            timezone=dt.timezone(dt.timedelta(hours=8)),
            minimum_items=5,
            fallback_categories=["tech"],
            fallback_keywords=["technology", "software", "cloud", "chip", "semiconductor", "Apple", "startup"],
        )

        self.assertEqual(
            [item.title for item in selected],
            [
                "AI model changes game production",
                "Unity game tooling update",
                "Apple device launch adds new technology platform",
                "Cloud software startup raises new funding",
                "Chip company expands semiconductor production",
            ],
        )

    def test_select_top_items_deduplicates_same_event_from_different_sources(self):
        now = dt.datetime(2026, 7, 7, 2, 0, tzinfo=dt.timezone.utc)
        eurogamer_item = NewsItem(
            title='Compulsion Games and Double Fine confirm "Independence Day" from Xbox',
            url="https://www.gamesindustry.biz/compulsion-games-and-double-fine-confirm-independence-day-from-xbox",
            source="GamesIndustry.biz",
            published_at=now - dt.timedelta(minutes=30),
            summary=(
                "Compulsion Games and Double Fine 每 two formerly Xbox-owned developers now spun out "
                "from the Xbox family of studios as Microsoft enacts a deep round of cuts and divestitures "
                "每 have released statements about the changes. Read more"
            ),
            category="game",
        )
        verge_item = NewsItem(
            title="Former Xbox studios Double Fine and Compulsion will keep games after going indie",
            url="https://www.theverge.com/news/701629/double-fine-compulsion-xbox-independent",
            source="The Verge",
            published_at=now,
            summary=(
                "Microsoft is spinning off four of its Xbox game studios - Compulsion Games, "
                "Double Fine Productions, Ninja Theory, and Undead Labs - as part of the restructuring "
                "announced today. However, two that are going independent, Double Fine and Compulsion, "
                "will get to keep their franchises and games catalogs"
            ),
            category="tech",
        )

        selected = select_top_items(
            [eurogamer_item, verge_item],
            keywords=["game", "games", "gaming"],
            exclude_keywords=[],
            max_items=5,
            lookback_hours=24,
            now=now,
            minimum_items=5,
            fallback_categories=["tech"],
            fallback_keywords=["technology", "software"],
        )

        self.assertEqual(selected, [verge_item])

    def test_select_top_items_reserves_configured_topic_categories(self):
        now = dt.datetime(2026, 8, 4, 2, 0, tzinfo=dt.timezone.utc)
        items = [
            NewsItem(
                title="国务院部署重大政策改革和民生工作",
                url="https://example.com/politics-1",
                source="时政源",
                published_at=now,
                category="politics",
            ),
            NewsItem(
                title="全国人大审议重要政策改革议题",
                url="https://example.com/politics-2",
                source="时政源",
                published_at=now - dt.timedelta(minutes=1),
                category="politics",
            ),
            NewsItem(
                title="政协围绕民生政策改革开展协商",
                url="https://example.com/politics-3",
                source="时政源",
                published_at=now - dt.timedelta(minutes=2),
                category="politics",
            ),
            NewsItem(
                title="外交工作会议部署政策改革任务",
                url="https://example.com/politics-4",
                source="时政源",
                published_at=now - dt.timedelta(minutes=3),
                category="politics",
            ),
            NewsItem(
                title="公安部部署夏季治安行动",
                url="https://example.com/security",
                source="法治源",
                published_at=now - dt.timedelta(hours=1),
                category="public_security",
            ),
            NewsItem(
                title="财政部公布年度预算安排",
                url="https://example.com/finance",
                source="财经源",
                published_at=now - dt.timedelta(hours=1),
                category="finance",
            ),
            NewsItem(
                title="科技部发布人工智能创新规划",
                url="https://example.com/technology",
                source="科技源",
                published_at=now - dt.timedelta(hours=1),
                category="technology",
            ),
        ]

        selected = select_top_items(
            items,
            keywords=["公安", "治安", "政策", "改革", "民生", "财政", "预算", "科技", "人工智能"],
            exclude_keywords=[],
            max_items=4,
            lookback_hours=24,
            now=now,
            category_minimums={
                "public_security": 1,
                "politics": 1,
                "finance": 1,
                "technology": 1,
            },
        )

        self.assertEqual(
            {item.category for item in selected},
            {"public_security", "politics", "finance", "technology"},
        )

    def test_select_top_items_deduplicates_similar_chinese_titles(self):
        now = dt.datetime(2026, 8, 4, 2, 0, tzinfo=dt.timezone.utc)
        older = NewsItem(
            title="公安部部署夏季治安打击整治行动",
            url="https://example.com/security-action-a",
            source="来源甲",
            published_at=now - dt.timedelta(minutes=10),
            category="public_security",
        )
        newer = NewsItem(
            title="公安部：部署夏季治安打击整治行动",
            url="https://example.com/security-action-b",
            source="来源乙",
            published_at=now,
            category="public_security",
        )

        selected = select_top_items(
            [older, newer],
            keywords=["公安", "治安"],
            exclude_keywords=[],
            max_items=5,
            lookback_hours=24,
            now=now,
        )

        self.assertEqual(selected, [newer])

    def test_select_top_items_limits_one_category_from_dominating(self):
        now = dt.datetime(2026, 8, 4, 2, 0, tzinfo=dt.timezone.utc)
        items = [
            NewsItem("人工智能芯片发布", "https://example.com/tech-1", "科技源", now, category="technology"),
            NewsItem("航天科研任务完成", "https://example.com/tech-2", "科技源", now, category="technology"),
            NewsItem("半导体产业技术升级", "https://example.com/tech-3", "科技源", now, category="technology"),
            NewsItem("数字经济数据平台上线", "https://example.com/tech-4", "科技源", now, category="technology"),
            NewsItem("国务院部署民生改革", "https://example.com/politics-1", "时政源", now, category="politics"),
            NewsItem("全国人大审议法律草案", "https://example.com/politics-2", "时政源", now, category="politics"),
            NewsItem("外交会议发布重要政策", "https://example.com/politics-3", "时政源", now, category="politics"),
        ]

        selected = select_top_items(
            items,
            keywords=["人工智能", "芯片", "航天", "科研", "半导体", "技术", "数字经济", "数据", "国务院", "民生", "改革", "全国人大", "法律", "外交", "会议", "政策"],
            exclude_keywords=[],
            max_items=4,
            lookback_hours=24,
            now=now,
            category_maximums={"technology": 2},
        )

        self.assertEqual(sum(item.category == "technology" for item in selected), 2)
        self.assertEqual(sum(item.category == "politics" for item in selected), 2)


if __name__ == "__main__":
    unittest.main()
