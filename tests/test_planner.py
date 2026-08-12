from datetime import date, datetime, time
from pathlib import Path
import unittest

from publisher.models import BookConfig, Chapter, PublishMode
from publisher.planner import build_schedule


def chapter(number: int, character_count: int) -> Chapter:
    return Chapter(
        relative_path=Path(f"第{number:03d}章-测试.txt"),
        number=number,
        title=f"测试{number}",
        character_count=character_count,
        sha256=str(number),
    )


def config_for(mode: PublishMode, limit: int, publish_time: time) -> BookConfig:
    return BookConfig(
        book_id="robot",
        name="机器人",
        source_dir=Path("C:/novels/robot"),
        publish_time=publish_time,
        mode=mode,
        limit=limit,
        next_chapter=1,
    )


class PlannerTests(unittest.TestCase):
    def test_word_mode_keeps_each_day_within_the_user_limit(self):
        chapters = [chapter(1, 4), chapter(2, 5), chapter(3, 6)]
        config = config_for(PublishMode.WORDS, 10, time(6, 30))

        schedule = build_schedule(chapters, config, date(2026, 7, 27))

        self.assertEqual(
            [[item.number for item in day.chapters] for day in schedule],
            [[1, 2], [3]],
        )
        self.assertEqual(schedule[0].publish_at, datetime(2026, 7, 27, 6, 30))

    def test_chapter_mode_uses_the_user_selected_count(self):
        chapters = [chapter(1, 9), chapter(2, 9), chapter(3, 9)]
        config = config_for(PublishMode.CHAPTERS, 2, time(0, 0))

        schedule = build_schedule(chapters, config, date(2026, 7, 27))

        self.assertEqual([len(day.chapters) for day in schedule], [2, 1])

    def test_oversized_single_chapter_is_flagged_in_word_mode(self):
        config = config_for(PublishMode.WORDS, 10, time(0, 0))

        schedule = build_schedule([chapter(1, 11)], config, date(2026, 7, 27))

        self.assertTrue(schedule[0].over_limit)
