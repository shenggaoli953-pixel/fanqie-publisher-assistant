from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Event


@dataclass(frozen=True)
class ActivityEntry:
    recorded_at: datetime
    operation: str
    state: str
    chapter_number: int | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "recorded_at": self.recorded_at.isoformat(),
            "operation": self.operation,
            "state": self.state,
            "chapter_number": self.chapter_number,
            "error_category": self.error_category,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ActivityEntry":
        if not isinstance(value, dict):
            raise ValueError("活动记录格式无效")
        chapter_number = value.get("chapter_number")
        return cls(
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            operation=str(value["operation"]),
            state=str(value["state"]),
            chapter_number=int(chapter_number) if chapter_number is not None else None,
            error_category=(
                str(value["error_category"])
                if value.get("error_category") is not None
                else None
            ),
        )


class RunControl:
    def __init__(self) -> None:
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()


class ActivityLog:
    _MAX_ENTRIES = 500

    def __init__(self, workspace_dir: Path) -> None:
        self._path = workspace_dir / "activity.json"

    def append(
        self,
        operation: str,
        state: str,
        *,
        chapter_number: int | None = None,
        error: str | None = None,
    ) -> ActivityEntry:
        entry = ActivityEntry(
            datetime.now(UTC),
            operation,
            state,
            chapter_number,
            _error_category(error),
        )
        entries = [*self.recent(), entry][-self._MAX_ENTRIES :]
        self._write(entries)
        return entry

    def recent(self) -> tuple[ActivityEntry, ...]:
        if not self._path.exists():
            return ()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("活动记录格式无效")
        return tuple(ActivityEntry.from_dict(item) for item in payload)

    def _write(self, entries: list[ActivityEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps([entry.to_dict() for entry in entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self._path)


def _error_category(error: str | None) -> str | None:
    if not error:
        return None
    message = error.lower()
    if "登录" in error or "login" in message:
        return "login"
    if "网络" in error or "timeout" in message or "连接" in error:
        return "network"
    if "额度" in error or "字数" in error or "上限" in error:
        return "quota"
    if "风险" in error or "检测" in error or "审核" in error:
        return "content_check"
    return "unknown"
