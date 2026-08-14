import hashlib
from dataclasses import dataclass
from pathlib import Path
import re

from publisher.models import Chapter


_CHAPTER_NAME_PATTERNS = (
    re.compile(r"^第\s*(\d+)\s*(?:章|回|节|话)(?:[-_—\s]+)?(.*?)$"),
    re.compile(
        r"^(?:chapter|chap|ch)[-_—\s]*(\d+)(?:[-_—\s]+)?(.*?)$",
        flags=re.IGNORECASE,
    ),
    re.compile(r"^(\d+)(?:[-_—\s]+)(.*?)$"),
)
_SUPPORTED_CHAPTER_SUFFIXES = {".txt", ".md"}
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


class ChapterParseError(ValueError):
    pass


@dataclass(frozen=True)
class DetectedProject:
    name: str
    source_dir: Path
    first_chapter: int
    chapter_count: int


def discover_project(selected_dir: Path) -> DetectedProject:
    if not selected_dir.is_dir():
        raise ChapterParseError(f"所选目录不存在: {selected_dir}")

    named_body_dir = selected_dir / "10-正文"
    candidates = [
        path
        for path in (named_body_dir, selected_dir)
        if path.is_dir()
    ]
    detected: list[tuple[Path, list[Chapter]]] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            detected.append((candidate, scan_chapters(candidate)))
        except ChapterParseError as error:
            errors.append(f"{candidate}: {error}")

    if not detected:
        details = "\n".join(errors) if errors else "目录中没有可识别的 .txt 或 .md 章节"
        raise ChapterParseError(f"未能识别正文目录:\n{details}")

    source_dir, chapters = max(
        detected,
        key=lambda item: (len(item[1]), item[0].name == "10-正文"),
    )
    project_dir = source_dir.parent if source_dir.name == "10-正文" else selected_dir
    return DetectedProject(
        name=project_dir.name,
        source_dir=source_dir,
        first_chapter=chapters[0].number,
        chapter_count=len(chapters),
    )


def scan_chapters(source_dir: Path) -> list[Chapter]:
    if not source_dir.is_dir():
        raise ChapterParseError(f"正文目录不存在: {source_dir}")

    chapters: list[Chapter] = []
    errors: list[str] = []
    seen_numbers: dict[int, Path] = {}

    paths = sorted(
        (
            path
            for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_CHAPTER_SUFFIXES
        ),
        key=lambda path: str(path.relative_to(source_dir)).lower(),
    )
    for path in paths:
        parsed_name = _parse_chapter_name(path.stem)
        if parsed_name is None:
            continue

        number, title = parsed_name
        if number in seen_numbers:
            errors.append(
                f"重复章节号 {number}: {seen_numbers[number].relative_to(source_dir)} 和 "
                f"{path.relative_to(source_dir)}"
            )
            continue

        body = _read_text(path)
        relative_path = path.relative_to(source_dir)
        seen_numbers[number] = path
        chapters.append(
            Chapter(
                relative_path=relative_path,
                number=number,
                title=title,
                character_count=len(re.sub(r"\s+", "", body)),
                sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            )
        )

    if errors:
        raise ChapterParseError("\n".join(errors))
    if not chapters:
        raise ChapterParseError("未找到可发布的 .txt 或 .md 章节")
    return sorted(chapters, key=lambda chapter: chapter.number)


def contiguous_chapters(
    chapters: list[Chapter], start_number: int, end_number: int | None
) -> list[Chapter]:
    chapters_by_number = {chapter.number: chapter for chapter in chapters}
    result: list[Chapter] = []
    number = start_number
    while end_number is None or number <= end_number:
        chapter = chapters_by_number.get(number)
        if chapter is None:
            return result
        result.append(chapter)
        number += 1
    return result


def read_chapter_body(source_dir: Path, chapter: Chapter) -> str:
    return _read_text(source_dir / chapter.relative_path)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            text = path.read_text(encoding=encoding)
            return _cleanup_markdown_headings(text) if path.suffix.lower() == ".md" else text
        except UnicodeDecodeError:
            continue
    raise ChapterParseError(f"无法读取章节编码: {path}")


def _parse_chapter_name(stem: str) -> tuple[int, str] | None:
    for pattern in _CHAPTER_NAME_PATTERNS:
        match = pattern.match(stem)
        if match is not None:
            return int(match.group(1)), match.group(2).strip()
    return None


def _cleanup_markdown_headings(text: str) -> str:
    return "\n".join(
        match.group(1) if (match := _MARKDOWN_HEADING.match(line)) else line
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )
