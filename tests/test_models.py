from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.models import BookConfig, PublishMode
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
        )

        self.assertEqual(BookConfig.from_dict(config.to_dict()), config)

    def test_repository_writes_and_reads_books(self):
        with TemporaryDirectory() as temp_dir:
            repository = JsonRepository(Path(temp_dir))
            repository.save_books([])

            self.assertEqual(repository.load_books(), [])
