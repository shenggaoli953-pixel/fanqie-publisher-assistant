from datetime import UTC, datetime
import json
from pathlib import Path

from publisher.models import BookState, ScheduledDay


def write_diagnostic_report(
    path: Path,
    *,
    version: str,
    state: BookState,
    schedule: list[ScheduledDay],
) -> Path:
    payload = {
        "format_version": 1,
        "app_version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "last_failed_chapter": state.last_failed_chapter,
        "last_error_category": _error_category(state.last_error),
        "schedule": [
            {
                "publish_at": day.publish_at.isoformat(),
                "chapter_number": chapter.number,
                "character_count": chapter.character_count,
                "status": day.status,
                "over_limit": day.over_limit,
            }
            for day in schedule
            for chapter in day.chapters
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return path


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
