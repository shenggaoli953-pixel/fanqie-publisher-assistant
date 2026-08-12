from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path


class PublishMode(StrEnum):
    WORDS = "words"
    CHAPTERS = "chapters"


@dataclass(frozen=True)
class BookConfig:
    book_id: str
    name: str
    source_dir: Path
    publish_time: time
    mode: PublishMode
    limit: int
    next_chapter: int
    publish_start_date: date | None = None
    publish_end_chapter: int | None = None
    ai_generated: bool = True

    def __post_init__(self) -> None:
        if not self.book_id.strip():
            raise ValueError("book_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if self.limit <= 0:
            raise ValueError("limit must be greater than zero")
        if self.next_chapter <= 0:
            raise ValueError("next_chapter must be greater than zero")
        if self.publish_end_chapter is not None and self.publish_end_chapter <= 0:
            raise ValueError("publish_end_chapter must be greater than zero")

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "book_id": self.book_id,
            "name": self.name,
            "source_dir": str(self.source_dir),
            "publish_time": self.publish_time.isoformat(timespec="minutes"),
            "mode": self.mode.value,
            "limit": self.limit,
            "next_chapter": self.next_chapter,
            "publish_start_date": (
                self.publish_start_date.isoformat()
                if self.publish_start_date is not None
                else None
            ),
            "publish_end_chapter": self.publish_end_chapter,
            "ai_generated": self.ai_generated,
        }

    @classmethod
    def from_dict(cls, value: dict[str, str | int]) -> "BookConfig":
        return cls(
            book_id=str(value["book_id"]),
            name=str(value["name"]),
            source_dir=Path(str(value["source_dir"])),
            publish_time=time.fromisoformat(str(value["publish_time"])),
            mode=PublishMode(str(value["mode"])),
            limit=int(value["limit"]),
            next_chapter=int(value["next_chapter"]),
            publish_start_date=(
                date.fromisoformat(str(value["publish_start_date"]))
                if value.get("publish_start_date")
                else None
            ),
            publish_end_chapter=(
                int(value["publish_end_chapter"])
                if value.get("publish_end_chapter") is not None
                else None
            ),
            ai_generated=bool(value.get("ai_generated", True)),
        )


@dataclass(frozen=True)
class Chapter:
    relative_path: Path
    number: int
    title: str
    character_count: int
    sha256: str


@dataclass(frozen=True)
class RemoteChapter:
    chapter_number: int
    character_count: int
    publish_at: datetime | None


@dataclass(frozen=True)
class ScheduledDay:
    publish_at: datetime
    chapters: tuple[Chapter, ...]
    over_limit: bool = False
    status: str = "pending"

    @property
    def character_count(self) -> int:
        return sum(chapter.character_count for chapter in self.chapters)


@dataclass(frozen=True)
class BatchConfirmation:
    token: str
    chapter_numbers: tuple[int, ...]
    expires_at: datetime


@dataclass(frozen=True)
class BookState:
    book_id: str
    schedule: tuple[ScheduledDay, ...]
    submitted_chapters: tuple[int, ...] = ()
    confirmation: BatchConfirmation | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "book_id": self.book_id,
            "schedule": [_scheduled_day_to_dict(day) for day in self.schedule],
            "submitted_chapters": list(self.submitted_chapters),
            "confirmation": _confirmation_to_dict(self.confirmation),
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "BookState":
        raw_confirmation = value.get("confirmation")
        return cls(
            book_id=str(value["book_id"]),
            schedule=tuple(
                _scheduled_day_from_dict(item) for item in value.get("schedule", [])
            ),
            submitted_chapters=tuple(
                int(number) for number in value.get("submitted_chapters", [])
            ),
            confirmation=(
                _confirmation_from_dict(raw_confirmation)
                if isinstance(raw_confirmation, dict)
                else None
            ),
            last_error=(
                str(value["last_error"]) if value.get("last_error") is not None else None
            ),
        )


def _chapter_to_dict(chapter: Chapter) -> dict[str, str | int]:
    return {
        "relative_path": str(chapter.relative_path),
        "number": chapter.number,
        "title": chapter.title,
        "character_count": chapter.character_count,
        "sha256": chapter.sha256,
    }


def _chapter_from_dict(value: object) -> Chapter:
    if not isinstance(value, dict):
        raise ValueError("chapter must be an object")
    return Chapter(
        relative_path=Path(str(value["relative_path"])),
        number=int(value["number"]),
        title=str(value["title"]),
        character_count=int(value["character_count"]),
        sha256=str(value["sha256"]),
    )


def _scheduled_day_to_dict(day: ScheduledDay) -> dict[str, object]:
    return {
        "publish_at": day.publish_at.isoformat(),
        "chapters": [_chapter_to_dict(chapter) for chapter in day.chapters],
        "over_limit": day.over_limit,
        "status": day.status,
    }


def _scheduled_day_from_dict(value: object) -> ScheduledDay:
    if not isinstance(value, dict):
        raise ValueError("scheduled day must be an object")
    raw_chapters = value.get("chapters", [])
    if not isinstance(raw_chapters, list):
        raise ValueError("scheduled day chapters must be a list")
    return ScheduledDay(
        publish_at=datetime.fromisoformat(str(value["publish_at"])),
        chapters=tuple(_chapter_from_dict(item) for item in raw_chapters),
        over_limit=bool(value.get("over_limit", False)),
        status=str(value.get("status", "pending")),
    )


def _confirmation_to_dict(
    confirmation: BatchConfirmation | None,
) -> dict[str, object] | None:
    if confirmation is None:
        return None
    return {
        "token": confirmation.token,
        "chapter_numbers": list(confirmation.chapter_numbers),
        "expires_at": confirmation.expires_at.isoformat(),
    }


def _confirmation_from_dict(value: dict[str, object]) -> BatchConfirmation:
    return BatchConfirmation(
        token=str(value["token"]),
        chapter_numbers=tuple(int(number) for number in value["chapter_numbers"]),
        expires_at=datetime.fromisoformat(str(value["expires_at"])),
    )
