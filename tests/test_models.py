from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.models import BookConfig, BookState, PublishMode
from publisher.repository import JsonRepository


class ModelTests(unittest.TestCase):
    def test_config_round_trip_preserves_editable_policy(self):
        config = BookConfig(
            book_id="robot",
            name="机器人",
            source_dir=Path(r"C:\novels\robot"),
            publish_time=time(0, 0),
            mode=PublishMode.CHAPTERS,
            limit=3,
            next_chapter=1,
            publish_start_date=date(2026, 8, 1),
            publish_end_chapter=20,
            ai_generated=False,
            publish_times=(time(0, 0), time(12, 0), time(20, 0)),
        )

        self.assertEqual(BookConfig.from_dict(config.to_dict()), config)

    def test_legacy_book_config_uses_its_original_single_publish_time(self):
        config = BookConfig.from_dict(
            {
                "book_id": "robot",
                "name": "机器人",
                "source_dir": r"C:\novels\robot",
                "publish_time": "08:00",
                "mode": "chapters",
                "limit": 3,
                "next_chapter": 1,
            }
        )

        self.assertEqual(config.effective_publish_times, (time(8, 0),))

    def test_book_config_rejects_duplicate_or_descending_publish_times(self):
        values = dict(
            book_id="robot",
            name="机器人",
            source_dir=Path(r"C:\novels\robot"),
            publish_time=time(8, 0),
            mode=PublishMode.CHAPTERS,
            limit=3,
            next_chapter=1,
        )

        with self.assertRaisesRegex(ValueError, "publish_times"):
            BookConfig(**values, publish_times=(time(8, 0), time(8, 0)))
        with self.assertRaisesRegex(ValueError, "publish_times"):
            BookConfig(**values, publish_times=(time(12, 0), time(8, 0)))

    def test_book_state_round_trip_preserves_last_failed_chapter(self):
        state = BookState(
            book_id="robot",
            schedule=(),
            last_error="network error",
            last_failed_chapter=8,
        )

        self.assertEqual(BookState.from_dict(state.to_dict()), state)

    def test_repository_writes_and_reads_books(self):
        with TemporaryDirectory() as temp_dir:
            repository = JsonRepository(Path(temp_dir))
            repository.save_books([])

            self.assertEqual(repository.load_books(), [])
