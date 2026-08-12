import json
from pathlib import Path

from publisher.models import BookConfig, BookState
from publisher.short_story import ShortStoryConfig


class JsonRepository:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _books_path(self) -> Path:
        return self._data_dir / "books.json"

    def load_books(self) -> list[BookConfig]:
        if not self._books_path.exists():
            return []
        payload = json.loads(self._books_path.read_text(encoding="utf-8"))
        return [BookConfig.from_dict(item) for item in payload]

    def save_books(self, books: list[BookConfig]) -> None:
        self._write_json(self._books_path, [book.to_dict() for book in books])

    @property
    def _short_stories_path(self) -> Path:
        return self._data_dir / "short_stories.json"

    def load_short_stories(self) -> list[ShortStoryConfig]:
        if not self._short_stories_path.exists():
            return []
        payload = json.loads(self._short_stories_path.read_text(encoding="utf-8"))
        return [ShortStoryConfig.from_dict(item) for item in payload]

    def save_short_stories(self, stories: list[ShortStoryConfig]) -> None:
        self._write_json(
            self._short_stories_path,
            [story.to_dict() for story in stories],
        )

    def load_state(self, book_id: str) -> BookState | None:
        path = self._state_path(book_id)
        if not path.exists():
            return None
        return BookState.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_state(self, state: BookState) -> None:
        self._write_json(self._state_path(state.book_id), state.to_dict())

    def _state_path(self, book_id: str) -> Path:
        safe_id = "".join(
            character for character in book_id if character.isalnum() or character in "-_"
        )
        if not safe_id:
            raise ValueError("book_id has no usable filename characters")
        return self._data_dir / "state" / f"{safe_id}.json"

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
