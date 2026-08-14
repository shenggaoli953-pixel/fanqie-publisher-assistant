from dataclasses import replace
from datetime import date, time
import json
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from collections.abc import Callable
from uuid import uuid4

from publisher.browser import EdgePublisherGateway, PreflightStatus, PublishDraft
from publisher.chapters import ChapterParseError, discover_project, read_chapter_body
from publisher.diagnostics import write_diagnostic_report
from publisher.models import BookConfig, PublishMode, RemoteChapter, ScheduledDay
from publisher.service import PublishingService
from publisher.short_story import (
    SHORT_STORY_EXTRA_CATEGORIES,
    SHORT_STORY_PRIMARY_CATEGORIES,
    ShortStoryConfig,
    scan_short_story_source,
    suggest_short_story_categories,
)
from publisher.workflows import (
    PublishRunReport,
    ShortStoryQueueReport,
    ShortStoryRunReport,
    publish_all_scheduled,
    publish_all_short_stories,
    publish_short_story,
    sync_novel_status,
)


_STATUS_LABELS = {
    "pending": "待发布",
    "partial": "部分完成",
    "submitted": "已提交",
}

_SHORT_STORY_CATEGORIES = SHORT_STORY_PRIMARY_CATEGORIES
_SHORT_STORY_EXTRA_TAGS = SHORT_STORY_EXTRA_CATEGORIES

_DEFAULT_UI_THEME = "Codex 浅色"
_UI_THEME_SETTINGS_VERSION = 3
_LEGACY_UI_THEMES = {
    "简白橙": _DEFAULT_UI_THEME,
    "暖灰橙": "Codex 暖灰",
    "玫瑰灰": "Codex 柔白",
    "石墨夜": "Codex 石墨",
    "Codex 浅色": "Codex 浅色",
}
_BODY_FONT = ("Segoe UI Variable Text", 10)
_BODY_BOLD_FONT = ("Segoe UI Variable Text Semibold", 10)
_TITLE_FONT = ("Segoe UI Variable Display Semib", 18)
_CONTEXT_TITLE_FONT = ("Segoe UI Variable Display Semib", 15)
_APP_VERSION = "0.2.0"
_UI_THEMES: dict[str, dict[str, str]] = {
    "Codex 浅色": {
        "canvas": "#F7F7F8",
        "surface": "#FFFFFF",
        "sidebar": "#F0F0F0",
        "header": "#FFFFFF",
        "header_status": "#F0F0F0",
        "header_foreground": "#1F1F1F",
        "text": "#1F1F1F",
        "title": "#1F1F1F",
        "muted": "#707070",
        "sidebar_text": "#404040",
        "section": "#303030",
        "primary": "#1F1F1F",
        "primary_foreground": "#FFFFFF",
        "primary_active": "#000000",
        "disabled_background": "#E2E2E2",
        "disabled_foreground": "#919191",
        "secondary": "#F3F3F3",
        "secondary_foreground": "#303030",
        "secondary_active": "#E7E7E7",
        "entry_border": "#E0E0E0",
        "info": "#F8F8F8",
        "separator": "#E7E7E7",
        "tab": "#F2F2F2",
        "tab_foreground": "#6E6E6E",
        "table": "#FFFFFF",
        "table_heading": "#F7F7F7",
        "table_border": "#E4E4E4",
        "table_selection": "#EAEAEA",
        "table_selection_foreground": "#1F1F1F",
        "list": "#FAFAFA",
        "list_foreground": "#282828",
        "list_selection": "#EAEAEA",
        "list_selection_foreground": "#1F1F1F",
        "focus": "#5F5F5F",
        "alternate": "#FAFAFA",
        "pending": "#A14D32",
        "partial": "#966200",
        "submitted": "#5D6B52",
        "over_limit": "#B53E3A",
    },
    "Codex 柔白": {
        "canvas": "#FBFBFC",
        "surface": "#FFFFFF",
        "sidebar": "#F7F7F8",
        "header": "#FFFFFF",
        "header_status": "#F3F3F4",
        "header_foreground": "#191919",
        "text": "#222222",
        "title": "#151515",
        "muted": "#777777",
        "sidebar_text": "#454545",
        "section": "#2B2B2B",
        "primary": "#2A2A2A",
        "primary_foreground": "#FFFFFF",
        "primary_active": "#000000",
        "disabled_background": "#E8E8E9",
        "disabled_foreground": "#979797",
        "secondary": "#F5F5F6",
        "secondary_foreground": "#303030",
        "secondary_active": "#E9E9EA",
        "entry_border": "#E5E5E6",
        "info": "#FCFCFC",
        "separator": "#EBEBEC",
        "tab": "#F5F5F6",
        "tab_foreground": "#747474",
        "table": "#FFFFFF",
        "table_heading": "#FAFAFA",
        "table_border": "#E8E8E9",
        "table_selection": "#EDEDED",
        "table_selection_foreground": "#171717",
        "list": "#FFFFFF",
        "list_foreground": "#282828",
        "list_selection": "#EDEDED",
        "list_selection_foreground": "#171717",
        "focus": "#5A5A5A",
        "alternate": "#FCFCFC",
        "pending": "#A14D32",
        "partial": "#966200",
        "submitted": "#5D6B52",
        "over_limit": "#B53E3A",
    },
    "Codex 深色": {
        "canvas": "#212121",
        "surface": "#2B2B2B",
        "sidebar": "#171717",
        "header": "#202020",
        "header_status": "#353535",
        "header_foreground": "#F2F2F2",
        "text": "#ECECEC",
        "title": "#FFFFFF",
        "muted": "#B0B0B0",
        "sidebar_text": "#D0D0D0",
        "section": "#EEEEEE",
        "primary": "#F3F3F3",
        "primary_foreground": "#202020",
        "primary_active": "#DCDCDC",
        "disabled_background": "#454545",
        "disabled_foreground": "#8F8F8F",
        "secondary": "#383838",
        "secondary_foreground": "#E5E5E5",
        "secondary_active": "#454545",
        "entry_border": "#4A4A4A",
        "info": "#303030",
        "separator": "#3E3E3E",
        "tab": "#282828",
        "tab_foreground": "#B9B9B9",
        "table": "#2B2B2B",
        "table_heading": "#343434",
        "table_border": "#484848",
        "table_selection": "#454545",
        "table_selection_foreground": "#FFFFFF",
        "list": "#292929",
        "list_foreground": "#E8E8E8",
        "list_selection": "#454545",
        "list_selection_foreground": "#FFFFFF",
        "focus": "#C9C9C9",
        "alternate": "#303030",
        "pending": "#FFAC82",
        "partial": "#EAC766",
        "submitted": "#B7CC8F",
        "over_limit": "#FF9388",
    },
    "Codex 黑曜": {
        "canvas": "#0D0D0D",
        "surface": "#171717",
        "sidebar": "#111111",
        "header": "#0D0D0D",
        "header_status": "#242424",
        "header_foreground": "#F5F5F5",
        "text": "#EDEDED",
        "title": "#FFFFFF",
        "muted": "#A8A8A8",
        "sidebar_text": "#D0D0D0",
        "section": "#F0F0F0",
        "primary": "#FFFFFF",
        "primary_foreground": "#111111",
        "primary_active": "#DADADA",
        "disabled_background": "#373737",
        "disabled_foreground": "#858585",
        "secondary": "#252525",
        "secondary_foreground": "#E6E6E6",
        "secondary_active": "#303030",
        "entry_border": "#3B3B3B",
        "info": "#1D1D1D",
        "separator": "#303030",
        "tab": "#161616",
        "tab_foreground": "#B7B7B7",
        "table": "#191919",
        "table_heading": "#242424",
        "table_border": "#383838",
        "table_selection": "#363636",
        "table_selection_foreground": "#FFFFFF",
        "list": "#161616",
        "list_foreground": "#E8E8E8",
        "list_selection": "#363636",
        "list_selection_foreground": "#FFFFFF",
        "focus": "#FFFFFF",
        "alternate": "#1D1D1D",
        "pending": "#FFAF85",
        "partial": "#EBC969",
        "submitted": "#BED194",
        "over_limit": "#FF968B",
    },
    "Codex 石墨": {
        "canvas": "#242424",
        "surface": "#2E2E2E",
        "sidebar": "#1D1D1D",
        "header": "#242424",
        "header_status": "#383838",
        "header_foreground": "#F2F2F2",
        "text": "#ECECEC",
        "title": "#FFFFFF",
        "muted": "#B1B1B1",
        "sidebar_text": "#D4D4D4",
        "section": "#F0F0F0",
        "primary": "#B94D34",
        "primary_foreground": "#FFFFFF",
        "primary_active": "#A9412B",
        "disabled_background": "#444444",
        "disabled_foreground": "#8E8E8E",
        "secondary": "#393939",
        "secondary_foreground": "#E7E7E7",
        "secondary_active": "#474747",
        "entry_border": "#4C4C4C",
        "info": "#333333",
        "separator": "#424242",
        "tab": "#292929",
        "tab_foreground": "#B9B9B9",
        "table": "#2E2E2E",
        "table_heading": "#393939",
        "table_border": "#4A4A4A",
        "table_selection": "#4B3934",
        "table_selection_foreground": "#FFF2ED",
        "list": "#2A2A2A",
        "list_foreground": "#E8E8E8",
        "list_selection": "#4B3934",
        "list_selection_foreground": "#FFF2ED",
        "focus": "#EF9B85",
        "alternate": "#343434",
        "pending": "#FFAC82",
        "partial": "#EAC766",
        "submitted": "#B7CC8F",
        "over_limit": "#FF9388",
    },
    "Codex 暖灰": {
        "canvas": "#F5F4F2",
        "surface": "#FFFFFF",
        "sidebar": "#EEEDEB",
        "header": "#FFFFFF",
        "header_status": "#EDECE9",
        "header_foreground": "#282725",
        "text": "#2C2B29",
        "title": "#242321",
        "muted": "#777570",
        "sidebar_text": "#494744",
        "section": "#373532",
        "primary": "#403D39",
        "primary_foreground": "#FFFFFF",
        "primary_active": "#242220",
        "disabled_background": "#DFDDDA",
        "disabled_foreground": "#908D88",
        "secondary": "#F0EFED",
        "secondary_foreground": "#403D39",
        "secondary_active": "#E5E3E0",
        "entry_border": "#DEDCD8",
        "info": "#F8F7F5",
        "separator": "#E6E4E0",
        "tab": "#EFEEEB",
        "tab_foreground": "#74716C",
        "table": "#FFFFFF",
        "table_heading": "#F4F3F1",
        "table_border": "#E5E3DF",
        "table_selection": "#EAE8E4",
        "table_selection_foreground": "#2A2927",
        "list": "#FBFAF8",
        "list_foreground": "#353330",
        "list_selection": "#EAE8E4",
        "list_selection_foreground": "#2A2927",
        "focus": "#66625D",
        "alternate": "#F9F8F6",
        "pending": "#9B5131",
        "partial": "#956500",
        "submitted": "#667052",
        "over_limit": "#A94138",
    },
}


def _write_ui_theme(settings_path: Path, theme: str) -> None:
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "version": _UI_THEME_SETTINGS_VERSION,
                    "theme": theme,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(settings_path)
    except OSError:
        return


def _load_ui_theme(settings_path: Path | None) -> str:
    if settings_path is None or not settings_path.exists():
        return _DEFAULT_UI_THEME
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_UI_THEME
    if not isinstance(payload, dict):
        return _DEFAULT_UI_THEME
    theme = payload.get("theme")
    if payload.get("version") != _UI_THEME_SETTINGS_VERSION:
        theme = _LEGACY_UI_THEMES.get(theme, _DEFAULT_UI_THEME)
        _write_ui_theme(settings_path, theme)
    return theme if theme in _UI_THEMES else _DEFAULT_UI_THEME


def parse_publish_start_date(value: str) -> date | None:
    normalized = value.strip()
    return date.fromisoformat(normalized) if normalized else None


def parse_publish_end_chapter(value: str) -> int | None:
    normalized = value.strip()
    return int(normalized) if normalized else None


def parse_publish_times(value: str) -> tuple[time, ...]:
    normalized = value.strip().translate(
        str.maketrans({"，": ",", "；": ",", ";": ",", "、": ","})
    )
    if not normalized:
        raise ValueError("请至少填写一个发布时间")
    parsed: list[time] = []
    for part in normalized.split(","):
        pieces = part.strip().split(":")
        if len(pieces) != 2:
            raise ValueError("发布时间应为 HH:MM，可用逗号分隔多个时间")
        try:
            parsed.append(time(int(pieces[0]), int(pieces[1])))
        except ValueError as error:
            raise ValueError("发布时间应为 HH:MM，可用逗号分隔多个时间") from error
    publish_times = tuple(parsed)
    if (
        len(set(publish_times)) != len(publish_times)
        or tuple(sorted(publish_times)) != publish_times
    ):
        raise ValueError("发布时间不能重复，且必须按从早到晚排列")
    return publish_times


def asset_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / name


def format_schedule_rows(days: list[ScheduledDay]) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for day in days:
        status = "超限" if day.over_limit else _STATUS_LABELS.get(day.status, day.status)
        rows.append(
            (
                day.publish_at.strftime("%Y-%m-%d %H:%M"),
                format_schedule_summary(day),
                str(day.character_count),
                status,
            )
        )
    return rows


def schedule_row_tag(day: ScheduledDay) -> str:
    if day.over_limit:
        return "over-limit"
    if day.status in _STATUS_LABELS:
        return day.status
    return "pending"


def format_schedule_summary(day: ScheduledDay) -> str:
    chapter_numbers = "、".join(str(chapter.number) for chapter in day.chapters)
    return f"第{chapter_numbers}章（{len(day.chapters)}章）"


def format_schedule_detail_rows(day: ScheduledDay) -> list[tuple[str, str, str]]:
    return [
        (f"第{chapter.number}章", chapter.title, str(chapter.character_count))
        for chapter in day.chapters
    ]


def format_schedule_detail_title(day: ScheduledDay) -> str:
    return f"{day.publish_at.strftime('%Y-%m-%d %H:%M')} | {day.character_count} 字 | 当天章节"


def format_publish_confirmation(day: ScheduledDay, ai_generated: bool) -> str:
    chapters = "\n".join(
        f"第{chapter.number}章 {chapter.title}（{chapter.character_count}字）"
        for chapter in day.chapters
    )
    ai_label = "是" if ai_generated else "否"
    return (
        f"定时：{day.publish_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"{chapters}\n"
        f"总字数：{day.character_count}\n"
        f"AI生成：{ai_label}"
    )


def format_publish_preview_rows(days: list[ScheduledDay]) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for day in days:
        status = "超限" if day.over_limit else _STATUS_LABELS.get(day.status, day.status)
        for chapter in day.chapters:
            rows.append(
                (
                    f"第{chapter.number}章",
                    chapter.title,
                    str(chapter.character_count),
                    day.publish_at.strftime("%Y-%m-%d %H:%M"),
                    status,
                )
            )
    return rows


class PublisherApp:
    def __init__(
        self,
        root: tk.Tk,
        service: PublishingService,
        gateway: EdgePublisherGateway | Callable[[], EdgePublisherGateway],
        theme_settings_path: Path | None = None,
    ) -> None:
        self._root = root
        self._service = service
        self._gateway_provider = gateway
        self._gateway = gateway
        self._theme_settings_path = theme_settings_path
        self._selected_book_id: str | None = None
        self._selected_story_id: str | None = None
        self._task_events: Queue[tuple[str, object]] = Queue()
        self._task_running = False
        self._mode_var = tk.StringVar()
        self._limit_var = tk.StringVar()
        self._time_var = tk.StringVar()
        self._start_date_var = tk.StringVar()
        self._chapter_start_var = tk.StringVar()
        self._chapter_end_var = tk.StringVar()
        self._ai_generated_var = tk.BooleanVar(value=True)
        self._publish_state_var = tk.StringVar()
        self._book_name_var = tk.StringVar(value="未选择作品")
        self._source_var = tk.StringVar()
        self._detail_date_var = tk.StringVar(value="当天章节")
        self._failure_var = tk.StringVar()
        self._task_status_var = tk.StringVar(value="就绪")
        self._theme_name_var = tk.StringVar(value=_load_ui_theme(theme_settings_path))
        self._story_name_var = tk.StringVar()
        self._story_source_var = tk.StringVar()
        self._story_cover_var = tk.StringVar()
        self._story_category_var = tk.StringVar()
        self._story_extra_var = tk.StringVar()
        self._story_extra_choice_var = tk.StringVar()
        self._story_extra_count_var = tk.StringVar(value="附加分类（0/7）")
        self._story_ai_var = tk.BooleanVar(value=True)
        self._story_consent_var = tk.BooleanVar(value=False)
        self._story_info_var = tk.StringVar(value="添加短故事后会显示正文预览信息。")
        self._schedule_days: dict[str, ScheduledDay] = {}
        self._build_window()
        self._refresh_books()
        self._refresh_short_stories()
        self._root.after(100, self._drain_task_events)

    def _configure_styles(self, style: ttk.Style) -> None:
        style.theme_use("clam")
        palette = self._theme_palette()
        style.configure("App.TFrame", background=palette["canvas"])
        style.configure("Surface.TFrame", background=palette["surface"])
        style.configure("Sidebar.TFrame", background=palette["sidebar"])
        style.configure("Context.TFrame", background=palette["info"])
        style.configure("Config.TFrame", background=palette["info"])
        style.configure(
            "App.TLabel",
            background=palette["canvas"],
            foreground=palette["text"],
            font=_BODY_FONT,
        )
        style.configure(
            "Surface.TLabel",
            background=palette["surface"],
            foreground=palette["text"],
            font=_BODY_FONT,
        )
        style.configure(
            "Config.TLabel",
            background=palette["info"],
            foreground=palette["text"],
            font=_BODY_FONT,
        )
        style.configure(
            "ConfigMuted.TLabel",
            background=palette["info"],
            foreground=palette["muted"],
            font=_BODY_FONT,
        )
        style.configure(
            "Sidebar.TLabel",
            background=palette["sidebar"],
            foreground=palette["sidebar_text"],
            font=_BODY_BOLD_FONT,
        )
        style.configure(
            "Title.TLabel",
            background=palette["surface"],
            foreground=palette["title"],
            font=_TITLE_FONT,
        )
        style.configure(
            "ContextTitle.TLabel",
            background=palette["info"],
            foreground=palette["title"],
            font=_CONTEXT_TITLE_FONT,
        )
        style.configure(
            "ContextMeta.TLabel",
            background=palette["info"],
            foreground=palette["muted"],
            font=_BODY_FONT,
        )
        style.configure(
            "ContextState.TLabel",
            background=palette["info"],
            foreground=palette["section"],
            font=_BODY_BOLD_FONT,
        )
        style.configure(
            "Muted.TLabel",
            background=palette["surface"],
            foreground=palette["muted"],
            font=_BODY_FONT,
        )
        style.configure(
            "Section.TLabel",
            background=palette["surface"],
            foreground=palette["section"],
            font=_BODY_BOLD_FONT,
        )
        style.configure(
            "Primary.TButton",
            background=palette["primary"],
            foreground=palette["primary_foreground"],
            bordercolor=palette["primary"],
            lightcolor=palette["primary"],
            darkcolor=palette["primary"],
            font=_BODY_BOLD_FONT,
            padding=(18, 8),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", palette["primary_active"]),
                ("disabled", palette["disabled_background"]),
            ],
            foreground=[("disabled", palette["disabled_foreground"])],
        )
        style.configure(
            "Secondary.TButton",
            background=palette["secondary"],
            foreground=palette["secondary_foreground"],
            bordercolor=palette["entry_border"],
            lightcolor=palette["surface"],
            darkcolor=palette["entry_border"],
            font=_BODY_FONT,
            padding=(12, 7),
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("active", palette["secondary_active"]),
                ("disabled", palette["disabled_background"]),
            ],
            foreground=[("disabled", palette["disabled_foreground"])],
        )
        style.configure(
            "App.TEntry",
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            bordercolor=palette["entry_border"],
            lightcolor=palette["surface"],
            darkcolor=palette["entry_border"],
            font=_BODY_FONT,
            padding=(8, 6),
        )
        style.configure(
            "App.TCombobox",
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            background=palette["secondary"],
            bordercolor=palette["entry_border"],
            font=_BODY_FONT,
            padding=(7, 5),
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", palette["surface"])],
            foreground=[("readonly", palette["text"])],
        )
        style.configure(
            "App.TCheckbutton",
            background=palette["surface"],
            foreground=palette["section"],
            font=_BODY_FONT,
        )
        style.map(
            "App.TCheckbutton",
            background=[("active", palette["surface"])],
            foreground=[("active", palette["title"])],
        )
        style.configure(
            "Config.TCheckbutton",
            background=palette["info"],
            foreground=palette["section"],
            font=_BODY_FONT,
        )
        style.map(
            "Config.TCheckbutton",
            background=[("active", palette["info"])],
            foreground=[("active", palette["title"])],
        )
        style.configure(
            "Info.TLabelframe",
            background=palette["info"],
            foreground=palette["section"],
            bordercolor=palette["separator"],
            lightcolor=palette["separator"],
            darkcolor=palette["separator"],
            padding=0,
        )
        style.configure(
            "Info.TLabelframe.Label",
            background=palette["info"],
            foreground=palette["section"],
            font=_BODY_BOLD_FONT,
        )
        style.configure(
            "Info.TLabel",
            background=palette["info"],
            foreground=palette["text"],
            font=_BODY_FONT,
        )
        style.configure("App.TSeparator", background=palette["separator"])
        style.configure("App.TNotebook", background=palette["canvas"], borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            background=palette["tab"],
            foreground=palette["tab_foreground"],
            padding=(22, 10),
            font=_BODY_FONT,
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["title"])],
        )
        style.configure(
            "App.Treeview",
            background=palette["table"],
            fieldbackground=palette["table"],
            foreground=palette["text"],
            rowheight=38,
            font=_BODY_FONT,
            bordercolor=palette["table_border"],
            lightcolor=palette["table_border"],
            darkcolor=palette["table_border"],
        )
        style.configure(
            "App.Treeview.Heading",
            background=palette["table_heading"],
            foreground=palette["section"],
            bordercolor=palette["table_border"],
            lightcolor=palette["table_heading"],
            darkcolor=palette["table_heading"],
            font=_BODY_BOLD_FONT,
            relief="flat",
        )
        style.map(
            "App.Treeview",
            background=[("selected", palette["table_selection"])],
            foreground=[("selected", palette["table_selection_foreground"])],
        )
        style.configure(
            "Header.Horizontal.TProgressbar",
            background=palette["primary"],
            troughcolor=palette["header_status"],
            bordercolor=palette["header_status"],
            lightcolor=palette["primary"],
            darkcolor=palette["primary"],
            borderwidth=0,
        )
        style.configure(
            "Header.TCombobox",
            fieldbackground=palette["header_status"],
            foreground=palette["header_foreground"],
            background=palette["header_status"],
            bordercolor=palette["header_status"],
            font=_BODY_FONT,
            padding=(7, 4),
        )
        style.map(
            "Header.TCombobox",
            fieldbackground=[("readonly", palette["header_status"])],
            foreground=[("readonly", palette["header_foreground"])],
        )

    def _theme_palette(self) -> dict[str, str]:
        return _UI_THEMES.get(self._theme_name_var.get(), _UI_THEMES[_DEFAULT_UI_THEME])

    def _save_selected_theme(self) -> None:
        if self._theme_settings_path is None:
            return
        _write_ui_theme(self._theme_settings_path, self._theme_name_var.get())

    def _configure_listbox_theme(self, widget: tk.Listbox, palette: dict[str, str]) -> None:
        widget.configure(
            background=palette["list"],
            foreground=palette["list_foreground"],
            selectbackground=palette["list_selection"],
            selectforeground=palette["list_selection_foreground"],
            highlightbackground=palette["entry_border"],
            highlightcolor=palette["focus"],
        )

    def _configure_schedule_tags(self) -> None:
        palette = self._theme_palette()
        self._schedule.tag_configure("alternating-row", background=palette["alternate"])
        self._schedule.tag_configure("pending", foreground=palette["pending"])
        self._schedule.tag_configure("partial", foreground=palette["partial"])
        self._schedule.tag_configure("submitted", foreground=palette["submitted"])
        self._schedule.tag_configure("over-limit", foreground=palette["over_limit"])
        self._schedule_detail.tag_configure("alternating-row", background=palette["alternate"])

    def _apply_selected_theme(self, _event: object | None = None) -> None:
        if self._theme_name_var.get() not in _UI_THEMES:
            self._theme_name_var.set(_DEFAULT_UI_THEME)
        palette = self._theme_palette()
        self._configure_styles(ttk.Style(self._root))
        self._root.configure(background=palette["canvas"])
        self._header.configure(background=palette["header"])
        self._header_title_label.configure(
            background=palette["header"],
            foreground=palette["header_foreground"],
        )
        self._header_subtitle_label.configure(
            background=palette["header"],
            foreground=palette["muted"],
        )
        if self._header_icon_label is not None:
            self._header_icon_label.configure(background=palette["header"])
        self._header_status.configure(
            background=palette["header_status"],
            foreground=palette["header_foreground"],
        )
        for attribute in ("_books_list", "_stories_list", "_story_extra_list"):
            widget = getattr(self, attribute, None)
            if widget is not None:
                self._configure_listbox_theme(widget, palette)
        self._configure_schedule_tags()
        self._save_selected_theme()
        self._task_status_var.set(f"主题：{self._theme_name_var.get()}")

    def _build_window(self) -> None:
        palette = self._theme_palette()
        self._root.title("番茄创作发布助手")
        self._root.geometry("1180x800+40+40")
        self._root.minsize(980, 680)
        self._root.configure(background=palette["canvas"])
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(1, weight=1)

        style = ttk.Style(self._root)
        self._configure_styles(style)

        self._header = tk.Frame(self._root, background=palette["header"], height=64)
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.columnconfigure(2, weight=1)
        self._header.grid_propagate(False)
        self._header_icon_label: tk.Label | None = None
        try:
            self._window_icon = tk.PhotoImage(file=str(asset_path("publisher-icon.png")))
            self._root.iconphoto(True, self._window_icon)
            self._header_icon = self._window_icon.subsample(32, 32)
            self._header_icon_label = tk.Label(
                self._header,
                image=self._header_icon,
                background=palette["header"],
            )
            self._header_icon_label.grid(row=0, column=0, rowspan=2, padx=(20, 9), pady=10)
        except tk.TclError:
            self._window_icon = None
        self._header_title_label = tk.Label(
            self._header,
            text="番茄创作发布助手",
            background=palette["header"],
            foreground=palette["header_foreground"],
            font=_TITLE_FONT,
        )
        self._header_title_label.grid(row=0, column=1, padx=(0, 18), pady=(7, 0), sticky="sw")
        self._header_subtitle_label = tk.Label(
            self._header,
            text="创作工作台",
            background=palette["header"],
            foreground=palette["muted"],
            font=_BODY_FONT,
        )
        self._header_subtitle_label.grid(row=1, column=1, padx=(0, 18), pady=(0, 8), sticky="nw")
        self._theme_box = ttk.Combobox(
            self._header,
            textvariable=self._theme_name_var,
            values=tuple(_UI_THEMES),
            state="readonly",
            width=9,
            style="Header.TCombobox",
        )
        self._theme_box.grid(row=0, column=3, rowspan=2, padx=(8, 8))
        self._theme_box.bind("<<ComboboxSelected>>", self._apply_selected_theme)
        self._header_status = tk.Label(
            self._header,
            textvariable=self._task_status_var,
            background=palette["header_status"],
            foreground=palette["header_foreground"],
            font=_BODY_FONT,
            padx=12,
            pady=6,
            width=18,
            anchor="w",
        )
        self._header_status.grid(row=0, column=4, rowspan=2, padx=8, sticky="e")
        self._task_progress = ttk.Progressbar(
            self._header,
            mode="indeterminate",
            length=120,
            style="Header.Horizontal.TProgressbar",
        )
        self._task_progress.grid(row=0, column=5, rowspan=2, padx=(8, 20))

        notebook = ttk.Notebook(self._root, style="App.TNotebook")
        notebook.grid(row=1, column=0, sticky="nsew", padx=16, pady=(10, 12))
        novel_tab = ttk.Frame(notebook, style="App.TFrame")
        story_tab = ttk.Frame(notebook, style="App.TFrame")
        notebook.add(novel_tab, text="小说排程")
        notebook.add(story_tab, text="短故事发布")
        self._build_novel_tab(novel_tab)
        self._build_short_story_tab(story_tab)

    def _build_novel_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        books_frame = ttk.Frame(parent, style="Sidebar.TFrame", padding=(18, 18))
        books_frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(books_frame, text="作品", style="Sidebar.TLabel").pack(anchor="w")
        self._books_list = tk.Listbox(
            books_frame,
            width=24,
            exportselection=False,
            background="#FAFBFD",
            foreground="#29394B",
            selectbackground="#DCE9FA",
            selectforeground="#1E3A5F",
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            highlightcolor="#4F80B6",
            borderwidth=0,
            activestyle="none",
            font=_BODY_FONT,
        )
        self._configure_listbox_theme(self._books_list, self._theme_palette())
        self._books_list.pack(fill="both", expand=True, pady=(10, 10))
        self._books_list.bind("<<ListboxSelect>>", self._on_select_book)
        ttk.Button(
            books_frame,
            text="添加作品",
            command=self._open_add_book,
            style="Secondary.TButton",
        ).pack(fill="x")

        main_frame = ttk.Frame(parent, style="Surface.TFrame", padding=(22, 12))
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.columnconfigure(6, weight=1)
        main_frame.rowconfigure(6, weight=1)
        main_frame.rowconfigure(8, weight=1)

        self._book_context = ttk.Frame(main_frame, style="Context.TFrame", padding=(14, 5))
        self._book_context.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 8))
        self._book_context.columnconfigure(0, weight=1)
        ttk.Label(
            self._book_context,
            textvariable=self._book_name_var,
            style="ContextTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self._book_context,
            textvariable=self._publish_state_var,
            style="ContextState.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(18, 0))

        ttk.Label(main_frame, text="排程设置", style="Section.TLabel").grid(
            row=1, column=0, columnspan=7, sticky="w", pady=(0, 6)
        )
        self._settings_band = ttk.Frame(main_frame, style="Config.TFrame", padding=(12, 4))
        self._settings_band.grid(row=2, column=0, columnspan=7, sticky="ew")
        self._settings_band.columnconfigure(6, weight=1)
        ttk.Label(self._settings_band, text="每日限制方式", style="Config.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._mode_box = ttk.Combobox(
            self._settings_band,
            textvariable=self._mode_var,
            values=(PublishMode.WORDS.value, PublishMode.CHAPTERS.value),
            state="readonly",
            width=14,
            style="App.TCombobox",
        )
        self._mode_box.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(self._settings_band, text="限制值", style="Config.TLabel").grid(
            row=0, column=2, sticky="w"
        )
        self._limit_entry = ttk.Entry(
            self._settings_band,
            textvariable=self._limit_var,
            width=10,
            style="App.TEntry",
        )
        self._limit_entry.grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(
            self._settings_band,
            text="发布时间（可多个）",
            style="Config.TLabel",
        ).grid(row=0, column=4, sticky="w", padx=(18, 0))
        self._time_entry = ttk.Entry(
            self._settings_band,
            textvariable=self._time_var,
            width=22,
            style="App.TEntry",
        )
        self._time_entry.grid(row=0, column=5, sticky="w", padx=(8, 0))
        ttk.Button(
            self._settings_band,
            text="保存并重排",
            command=self._save_policy,
            style="Secondary.TButton",
        ).grid(
            row=0, column=6, sticky="e", padx=(18, 0)
        )

        ttk.Label(main_frame, text="发布范围", style="Section.TLabel").grid(
            row=3, column=0, columnspan=7, sticky="w", pady=(10, 5)
        )
        self._range_band = ttk.Frame(main_frame, style="Config.TFrame", padding=(12, 4))
        self._range_band.grid(row=4, column=0, columnspan=7, sticky="ew")
        self._range_band.columnconfigure(6, weight=1)
        ttk.Label(self._range_band, text="首个发布日期", style="Config.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(
            self._range_band,
            textvariable=self._start_date_var,
            width=12,
            style="App.TEntry",
        ).grid(
            row=0, column=1, sticky="w", padx=(8, 8)
        )
        ttk.Button(
            self._range_band,
            text="选择日期",
            command=lambda: self._open_date_picker(self._start_date_var, self._root),
            style="Secondary.TButton",
        ).grid(row=0, column=2, sticky="w")
        ttk.Button(
            self._range_band,
            text="暂不发布",
            command=self._pause_publishing,
            style="Secondary.TButton",
        ).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Label(
            self._range_band,
            textvariable=self._publish_state_var,
            style="ConfigMuted.TLabel",
        ).grid(
            row=0, column=4, columnspan=3, sticky="w", padx=(18, 0)
        )

        ttk.Label(self._range_band, text="起始章节", style="Config.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 0)
        )
        ttk.Entry(
            self._range_band,
            textvariable=self._chapter_start_var,
            width=8,
            style="App.TEntry",
        ).grid(
            row=1, column=1, sticky="w", padx=(8, 18), pady=(0, 0)
        )
        ttk.Label(self._range_band, text="结束章节（含）", style="Config.TLabel").grid(
            row=1, column=2, sticky="w", pady=(0, 0)
        )
        ttk.Entry(
            self._range_band,
            textvariable=self._chapter_end_var,
            width=8,
            style="App.TEntry",
        ).grid(
            row=1, column=3, sticky="w", padx=(8, 0), pady=(0, 0)
        )
        ttk.Label(self._range_band, text="留空不截止", style="ConfigMuted.TLabel").grid(
            row=1, column=4, sticky="w", padx=(18, 0), pady=(0, 0)
        )
        ttk.Checkbutton(
            self._range_band,
            text="AI生成：是",
            variable=self._ai_generated_var,
            style="Config.TCheckbutton",
        ).grid(row=1, column=5, columnspan=2, sticky="w", padx=(18, 0), pady=(0, 0))

        ttk.Label(main_frame, text="发布排程", style="Section.TLabel").grid(
            row=5, column=0, columnspan=7, sticky="nw", pady=(6, 4)
        )
        table_frame = ttk.Frame(main_frame, style="Surface.TFrame")
        table_frame.grid(row=6, column=0, columnspan=7, sticky="nsew", pady=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self._schedule = ttk.Treeview(
            table_frame,
            columns=("time", "chapters", "count", "status"),
            show="headings",
            style="App.Treeview",
            height=4,
        )
        for column, label, width in (
            ("time", "发布时间", 155),
            ("chapters", "章节", 320),
            ("count", "字数", 90),
            ("status", "状态", 112),
        ):
            self._schedule.heading(column, text=label)
            self._schedule.column(column, width=width, anchor="w")
        self._schedule.grid(row=0, column=0, sticky="nsew")
        self._schedule.bind("<<TreeviewSelect>>", self._on_select_schedule_day)
        scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self._schedule.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._schedule.configure(yscrollcommand=scrollbar.set)

        ttk.Label(main_frame, textvariable=self._detail_date_var, style="Section.TLabel").grid(
            row=7, column=0, columnspan=7, sticky="nw", pady=(0, 6)
        )
        detail_frame = ttk.Frame(main_frame, style="Surface.TFrame")
        detail_frame.grid(row=8, column=0, columnspan=7, sticky="nsew", pady=(0, 8))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self._schedule_detail = ttk.Treeview(
            detail_frame,
            columns=("number", "title", "count"),
            show="headings",
            style="App.Treeview",
            height=5,
        )
        for column, label, width in (
            ("number", "章节", 100),
            ("title", "标题", 560),
            ("count", "字数", 100),
        ):
            self._schedule_detail.heading(column, text=label)
            self._schedule_detail.column(
                column,
                width=width,
                anchor="w",
                stretch=column == "title",
            )
        self._schedule_detail.grid(row=0, column=0, sticky="nsew")
        self._configure_schedule_tags()
        detail_scrollbar = ttk.Scrollbar(
            detail_frame,
            orient="vertical",
            command=self._schedule_detail.yview,
        )
        detail_scrollbar.grid(row=0, column=1, sticky="ns")
        self._schedule_detail.configure(yscrollcommand=detail_scrollbar.set)

        actions = ttk.Frame(main_frame, style="Surface.TFrame")
        actions.grid(row=9, column=0, columnspan=7, sticky="ew", pady=(2, 0))
        self._open_edge_button = ttk.Button(
            actions,
            text="打开番茄后台",
            command=self._start_open_edge,
            style="Secondary.TButton",
        )
        self._open_edge_button.pack(side="left")
        self._sync_button = ttk.Button(
            actions,
            text="同步后台状态",
            command=self._start_check_edge,
            style="Secondary.TButton",
        )
        self._sync_button.pack(side="left", padx=(8, 0))
        self._preview_button = ttk.Button(
            actions,
            text="查看发布清单",
            command=self._open_publish_preview,
            style="Secondary.TButton",
        )
        self._preview_button.pack(side="left", padx=(8, 0))
        self._failure_label = ttk.Label(
            actions,
            textvariable=self._failure_var,
            style="Muted.TLabel",
        )
        self._recovery_button = ttk.Button(
            actions,
            text="从失败处继续",
            command=self._start_recovery_publish,
            style="Secondary.TButton",
        )
        self._diagnostic_button = ttk.Button(
            actions,
            text="导出诊断",
            command=self._export_diagnostics,
            style="Secondary.TButton",
        )
        self._publish_button = ttk.Button(
            actions,
            text="发布全部排程",
            command=self._start_publish_novel,
            style="Primary.TButton",
        )
        self._publish_button.pack(side="right")

    def _build_short_story_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(parent, style="Sidebar.TFrame", padding=(18, 18))
        sidebar.grid(row=0, column=0, sticky="nsew")
        ttk.Label(sidebar, text="短故事", style="Sidebar.TLabel").pack(anchor="w")
        self._stories_list = tk.Listbox(
            sidebar,
            width=24,
            exportselection=False,
            background="#FAFBFD",
            foreground="#29394B",
            selectbackground="#DCE9FA",
            selectforeground="#1E3A5F",
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            highlightcolor="#4F80B6",
            borderwidth=0,
            activestyle="none",
            font=_BODY_FONT,
        )
        self._configure_listbox_theme(self._stories_list, self._theme_palette())
        self._stories_list.pack(fill="both", expand=True, pady=(10, 10))
        self._stories_list.bind("<<ListboxSelect>>", self._on_select_short_story)
        ttk.Button(
            sidebar,
            text="添加短故事",
            command=self._new_short_story,
            style="Secondary.TButton",
        ).pack(fill="x")

        form = ttk.Frame(parent, style="Surface.TFrame", padding=(22, 18))
        form.grid(row=0, column=1, sticky="nsew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        self._story_context = ttk.Frame(form, style="Context.TFrame", padding=(16, 12))
        self._story_context.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 12))
        ttk.Label(
            self._story_context,
            text="短故事发布",
            style="ContextTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self._story_context,
            text="内容与发布安排",
            style="ContextMeta.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Separator(form, style="App.TSeparator").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(0, 8)
        )

        fields = (
            ("作品名称", self._story_name_var),
            ("正文文件或目录", self._story_source_var),
            ("封面图片", self._story_cover_var),
        )
        for row, (label, variable) in enumerate(fields, start=2):
            ttk.Label(form, text=label, style="Surface.TLabel").grid(
                row=row, column=0, sticky="w", pady=7
            )
            ttk.Entry(form, textvariable=variable, style="App.TEntry").grid(
                row=row, column=1, columnspan=2, sticky="ew", padx=(12, 8), pady=7
            )
        source_actions = ttk.Frame(form, style="Surface.TFrame")
        source_actions.grid(row=3, column=3, sticky="e", pady=7)
        ttk.Button(
            source_actions,
            text="文件",
            command=self._choose_story_source,
            style="Secondary.TButton",
        ).pack(side="left")
        ttk.Button(
            source_actions,
            text="目录",
            command=self._choose_story_source_dir,
            style="Secondary.TButton",
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            form,
            text="选择图片",
            command=self._choose_story_cover,
            style="Secondary.TButton",
        ).grid(
            row=4, column=3, sticky="e", pady=7
        )

        ttk.Label(form, text="主分类", style="Surface.TLabel").grid(
            row=5, column=0, sticky="w", pady=7
        )
        ttk.Combobox(
            form,
            textvariable=self._story_category_var,
            values=_SHORT_STORY_CATEGORIES,
            state="readonly",
            style="App.TCombobox",
        ).grid(row=5, column=1, sticky="ew", padx=(12, 8), pady=7)
        ttk.Label(form, text="添加分类", style="Surface.TLabel").grid(
            row=5, column=2, sticky="e", pady=7
        )
        extra_picker = ttk.Frame(form, style="Surface.TFrame")
        extra_picker.grid(row=5, column=3, sticky="ew", padx=(8, 0), pady=7)
        extra_picker.columnconfigure(0, weight=1)
        ttk.Combobox(
            extra_picker,
            textvariable=self._story_extra_choice_var,
            values=_SHORT_STORY_EXTRA_TAGS,
            state="readonly",
            style="App.TCombobox",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            extra_picker,
            text="添加",
            command=self._add_story_extra_category,
            style="Secondary.TButton",
        ).grid(row=0, column=1, padx=(6, 0))

        ttk.Label(
            form,
            textvariable=self._story_extra_count_var,
            style="Surface.TLabel",
        ).grid(row=6, column=0, sticky="nw", pady=(7, 4))
        extra_list_frame = ttk.Frame(form, style="Surface.TFrame")
        extra_list_frame.grid(
            row=6,
            column=1,
            columnspan=2,
            sticky="nsew",
            padx=(12, 8),
            pady=(7, 4),
        )
        extra_list_frame.columnconfigure(0, weight=1)
        self._story_extra_list = tk.Listbox(
            extra_list_frame,
            height=4,
            exportselection=False,
            background="#FAFBFD",
            foreground="#29394B",
            selectbackground="#DCE9FA",
            selectforeground="#1E3A5F",
            highlightthickness=1,
            highlightbackground="#CBD5E1",
            highlightcolor="#4F80B6",
            borderwidth=0,
            activestyle="none",
            font=_BODY_FONT,
        )
        self._configure_listbox_theme(self._story_extra_list, self._theme_palette())
        self._story_extra_list.grid(
            row=0, column=0, sticky="nsew"
        )
        self._story_extra_scrollbar = ttk.Scrollbar(
            extra_list_frame,
            orient="vertical",
            command=self._story_extra_list.yview,
        )
        self._story_extra_scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self._story_extra_list.configure(yscrollcommand=self._story_extra_scrollbar.set)
        ttk.Button(
            form,
            text="移除所选",
            command=self._remove_story_extra_category,
            style="Secondary.TButton",
        ).grid(row=6, column=3, sticky="e", pady=(7, 4))

        ttk.Checkbutton(
            form,
            text="AI 生成：是",
            variable=self._story_ai_var,
            style="App.TCheckbutton",
        ).grid(row=7, column=1, sticky="w", padx=(12, 0), pady=(10, 4))
        ttk.Button(
            form,
            text="重新识别",
            command=lambda: self._update_story_preview(force_category_suggestion=True),
            style="Secondary.TButton",
        ).grid(row=7, column=0, sticky="w", pady=(10, 4))
        ttk.Checkbutton(
            form,
            text="我已阅读番茄短故事发布事项",
            variable=self._story_consent_var,
            style="App.TCheckbutton",
        ).grid(row=7, column=2, columnspan=2, sticky="w", pady=(10, 4))

        info = ttk.LabelFrame(form, text="正文预览", padding=14, style="Info.TLabelframe")
        info.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=(18, 12))
        form.rowconfigure(8, weight=1)
        ttk.Label(
            info,
            textvariable=self._story_info_var,
            style="Info.TLabel",
            justify="left",
            wraplength=700,
        ).pack(anchor="nw", fill="x")

        actions = ttk.Frame(form, style="Surface.TFrame")
        actions.grid(row=9, column=0, columnspan=4, sticky="ew")
        ttk.Button(
            actions,
            text="保存设置",
            command=self._save_short_story,
            style="Secondary.TButton",
        ).pack(
            side="left"
        )
        ttk.Button(
            actions,
            text="在 Edge 中查看",
            command=self._start_open_edge,
            style="Secondary.TButton",
        ).pack(side="left", padx=(8, 0))
        self._story_publish_button = ttk.Button(
            actions,
            text="发布全部未发布短故事",
            command=self._start_publish_short_story,
            style="Primary.TButton",
        )
        self._story_publish_button.pack(side="right")

    def _refresh_short_stories(self) -> None:
        loader = getattr(self._service, "list_short_stories", lambda: [])
        self._stories = loader()
        self._stories_list.delete(0, tk.END)
        for story in self._stories:
            self._stories_list.insert(tk.END, story.name)
        if self._stories and self._selected_story_id is None:
            self._stories_list.selection_set(0)
            self._load_short_story(self._stories[0].story_id)

    def _on_select_short_story(self, _event: object) -> None:
        selection = self._stories_list.curselection()
        if selection:
            self._load_short_story(self._stories[selection[0]].story_id)

    def _load_short_story(self, story_id: str) -> None:
        story = self._service.get_short_story(story_id)
        self._selected_story_id = story_id
        self._story_name_var.set(story.name)
        self._story_source_var.set(str(story.source_path))
        self._story_cover_var.set(str(story.cover_path))
        self._story_category_var.set(story.primary_category)
        self._set_story_extra_categories(story.extra_categories)
        self._story_ai_var.set(story.ai_generated)
        self._story_consent_var.set(story.consent_confirmed)
        self._update_story_preview()
        if story.remote_draft_url:
            self._story_info_var.set(
                self._story_info_var.get()
                + "\n\n已保留番茄草稿，可在同一草稿上继续发布。"
            )

    def _new_short_story(self) -> None:
        self._selected_story_id = None
        self._stories_list.selection_clear(0, tk.END)
        self._story_name_var.set("")
        self._story_source_var.set("")
        self._story_cover_var.set("")
        self._story_category_var.set("")
        self._story_extra_choice_var.set("")
        self._set_story_extra_categories(())
        self._story_ai_var.set(True)
        self._story_consent_var.set(False)
        self._story_info_var.set("选择正文文件或目录后会自动读取标题、字数和文件数量。")

    def _choose_story_source(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self._root,
            title="选择短故事正文",
            filetypes=(("正文文件", "*.txt *.md"), ("所有文件", "*.*")),
        )
        if selected:
            self._story_source_var.set(selected)
            self._update_story_preview()

    def _choose_story_source_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self._root,
            title="选择短故事正文目录",
        )
        if selected:
            self._story_source_var.set(selected)
            self._update_story_preview()

    def _choose_story_cover(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self._root,
            title="选择短故事封面",
            filetypes=(("图片", "*.png *.jpg *.jpeg"), ("所有文件", "*.*")),
        )
        if selected:
            self._story_cover_var.set(selected)

    def _story_extra_categories(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip()
                for item in self._story_extra_var.get().split("、")
                if item.strip()
            )
        )

    def _set_story_extra_categories(self, categories: tuple[str, ...]) -> None:
        selected = tuple(
            category
            for category in dict.fromkeys(categories)
            if category in _SHORT_STORY_EXTRA_TAGS
        )[:7]
        self._story_extra_var.set("、".join(selected))
        self._story_extra_count_var.set(f"附加分类（{len(selected)}/7）")
        self._story_extra_list.delete(0, tk.END)
        for category in selected:
            self._story_extra_list.insert(tk.END, category)

    def _add_story_extra_category(self) -> None:
        category = self._story_extra_choice_var.get().strip()
        selected = self._story_extra_categories()
        if not category:
            self._task_status_var.set("请选择要添加的附加分类")
            return
        if category in selected:
            self._task_status_var.set(f"附加分类已包含：{category}")
            return
        if len(selected) >= 7:
            self._task_status_var.set("附加分类最多选择 7 个")
            return
        self._set_story_extra_categories((*selected, category))
        self._story_extra_choice_var.set("")

    def _remove_story_extra_category(self) -> None:
        selection = self._story_extra_list.curselection()
        if not selection:
            self._task_status_var.set("请先选中要移除的附加分类")
            return
        selected = list(self._story_extra_categories())
        del selected[selection[0]]
        self._set_story_extra_categories(tuple(selected))

    def _update_story_preview(self, force_category_suggestion: bool = False) -> None:
        source = Path(self._story_source_var.get().strip())
        try:
            draft = scan_short_story_source(source)
        except (OSError, ValueError) as error:
            self._story_info_var.set(str(error))
            return
        if not self._story_name_var.get().strip():
            self._story_name_var.set(draft.title)
        suggested_primary, suggested_extras = suggest_short_story_categories(
            draft.title, draft.body
        )
        if suggested_primary and (
            force_category_suggestion or not self._story_category_var.get().strip()
        ):
            self._story_category_var.set(suggested_primary)
        if suggested_extras and (
            force_category_suggestion or not self._story_extra_var.get().strip()
        ):
            self._set_story_extra_categories(suggested_extras)
        category_info = "自动分类：未识别，请手动选择"
        if suggested_primary:
            category_info = f"自动分类：主分类 {suggested_primary}"
            if suggested_extras:
                category_info += f"；附加分类 {'、'.join(suggested_extras)}"
        self._story_info_var.set(
            f"识别标题：{draft.title}\n"
            f"正文：{draft.character_count} 字\n"
            f"文件：{len(draft.source_files)} 个\n"
            f"{category_info}"
        )

    def _save_short_story(self) -> bool:
        story_id = self._selected_story_id or uuid4().hex
        old = (
            self._service.get_short_story(story_id)
            if self._selected_story_id is not None
            else None
        )
        extra_categories = self._story_extra_categories()
        try:
            config = ShortStoryConfig(
                story_id=story_id,
                name=self._story_name_var.get().strip(),
                source_path=Path(self._story_source_var.get().strip()),
                cover_path=Path(self._story_cover_var.get().strip()),
                primary_category=self._story_category_var.get().strip(),
                extra_categories=extra_categories,
                ai_generated=self._story_ai_var.get(),
                trial_enabled=True,
                consent_confirmed=self._story_consent_var.get(),
                remote_draft_url=(old.remote_draft_url if old is not None else None),
            )
            if old is None:
                self._service.add_short_story(config)
            else:
                self._service.update_short_story(config)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("无法保存短故事", str(error), parent=self._root)
            return False
        self._selected_story_id = story_id
        self._refresh_short_stories()
        self._load_short_story(story_id)
        self._task_status_var.set("短故事设置已保存")
        return True

    def _make_gateway(self):
        provider = self._gateway_provider
        return provider() if callable(provider) else provider

    def _start_task(
        self,
        label: str,
        operation: Callable[[], object],
        on_done: Callable[[object], None],
    ) -> None:
        if self._task_running:
            self._task_status_var.set("已有任务正在运行")
            return
        self._task_running = True
        self._task_done_handler = on_done
        self._task_status_var.set(label)
        self._task_progress.start(12)
        self._set_task_buttons_enabled(False)

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                self._task_events.put(("error", error))
            else:
                self._task_events.put(("done", result))

        Thread(target=worker, daemon=True).start()

    def _drain_task_events(self) -> None:
        try:
            while True:
                event, payload = self._task_events.get_nowait()
                if event == "progress":
                    self._task_status_var.set(str(payload))
                    continue
                self._task_running = False
                self._task_progress.stop()
                self._set_task_buttons_enabled(True)
                if event == "error":
                    self._task_status_var.set("任务已停止")
                    messagebox.showerror("任务未完成", str(payload), parent=self._root)
                else:
                    self._task_done_handler(payload)
        except Empty:
            pass
        self._root.after(100, self._drain_task_events)

    def _set_task_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for name in (
            "_open_edge_button",
            "_sync_button",
            "_publish_button",
            "_story_publish_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.configure(state=state)

    def _close_gateway(self, gateway) -> None:
        close = getattr(gateway, "close", None)
        if close is not None:
            close()

    def _start_open_edge(self) -> None:
        def operation() -> None:
            gateway = self._make_gateway()
            try:
                gateway.launch()
            finally:
                self._close_gateway(gateway)

        self._start_task(
            "正在打开 Edge",
            operation,
            lambda _result: self._task_status_var.set(
                "Edge 已打开，可从任务栏随时查看"
            ),
        )

    def _start_check_edge(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        book_id = self._selected_book_id

        def operation():
            gateway = self._make_gateway()
            try:
                return sync_novel_status(self._service, gateway, book_id)
            finally:
                self._close_gateway(gateway)

        def done(result) -> None:
            self._load_book(book_id)
            self._task_status_var.set(f"后台状态已同步，共 {result.remote_count} 章")

        self._start_task("正在读取番茄章节列表", operation, done)

    def _open_publish_preview(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        days = self._service.get_schedule(self._selected_book_id)
        if not days:
            messagebox.showinfo(
                "暂无发布清单",
                "请先设置首个发布日期并保存排程。",
                parent=self._root,
            )
            return

        dialog = tk.Toplevel(self._root)
        dialog.title("发布清单")
        dialog.transient(self._root)
        dialog.geometry("900x520")
        dialog.minsize(720, 360)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text="发布前核对章节、字数、时间与状态；不会读取或显示正文。",
            style="App.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 10))
        frame = ttk.Frame(dialog, style="Surface.TFrame")
        frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = ttk.Treeview(
            frame,
            columns=("number", "title", "count", "time", "status"),
            show="headings",
            style="App.Treeview",
        )
        for column, label, width in (
            ("number", "章节", 88),
            ("title", "标题", 300),
            ("count", "字数", 90),
            ("time", "发布时间", 160),
            ("status", "状态", 90),
        ):
            table.heading(column, text=label)
            table.column(column, width=width, anchor="w", stretch=column == "title")
        for row in format_publish_preview_rows(days):
            table.insert("", tk.END, values=row)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.configure(yscrollcommand=scrollbar.set)
        ttk.Button(
            dialog,
            text="关闭",
            command=dialog.destroy,
            style="Secondary.TButton",
        ).grid(row=2, column=0, sticky="e", padx=18, pady=(0, 16))

    def _start_recovery_publish(self) -> None:
        self._start_publish_novel()

    def _export_diagnostics(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        destination = filedialog.asksaveasfilename(
            parent=self._root,
            title="导出诊断信息",
            defaultextension=".json",
            initialfile="fanqie-publisher-diagnostic.json",
            filetypes=(("JSON 文件", "*.json"),),
        )
        if not destination:
            return
        try:
            report = write_diagnostic_report(
                Path(destination),
                version=_APP_VERSION,
                state=self._service.get_book_state(self._selected_book_id),
                schedule=self._service.get_schedule(self._selected_book_id),
            )
        except (OSError, KeyError, ValueError) as error:
            messagebox.showerror("导出失败", str(error), parent=self._root)
            return
        messagebox.showinfo(
            "诊断已导出",
            f"已保存诊断信息：{report.name}\n文件不包含正文、标题、路径、账号或登录信息。",
            parent=self._root,
        )

    def _start_publish_novel(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        book_id = self._selected_book_id
        book = self._service.get_book(book_id)
        if book.publish_start_date is None:
            messagebox.showinfo(
                "作品暂不发布",
                "请先设置首个发布日期并保存。",
                parent=self._root,
            )
            return

        def operation() -> PublishRunReport:
            gateway = self._make_gateway()
            try:
                return publish_all_scheduled(
                    self._service,
                    gateway,
                    book_id,
                    read_body=read_chapter_body,
                    on_progress=lambda message: self._task_events.put(
                        ("progress", message)
                    ),
                )
            finally:
                self._close_gateway(gateway)

        def done(report: PublishRunReport) -> None:
            self._load_book(book_id)
            if not report.success:
                self._task_status_var.set("发布已停止")
                messagebox.showerror(
                    "发布未完成",
                    f"第{report.failed_chapter}章：{report.error}",
                    parent=self._root,
                )
                return
            count = len(report.submitted_numbers)
            self._task_status_var.set(
                f"发布完成，共提交 {count} 章" if count else "后台已是最新状态"
            )
            if count:
                messagebox.showinfo(
                    "发布完成",
                    f"已连续提交 {count} 章，全部排程处理完成。",
                    parent=self._root,
                )

        self._start_task("正在准备整批发布", operation, done)

    def _start_publish_short_story(self) -> None:
        if not self._save_short_story() or self._selected_story_id is None:
            return

        def operation() -> ShortStoryQueueReport:
            gateway = self._make_gateway()
            try:
                return publish_all_short_stories(
                    self._service,
                    gateway,
                    on_progress=lambda message: self._task_events.put(
                        ("progress", message)
                    ),
                )
            finally:
                self._close_gateway(gateway)

        def done(report: ShortStoryQueueReport) -> None:
            self._refresh_short_stories()
            if report.success:
                if report.submitted_names:
                    self._task_status_var.set(
                        f"短故事发布完成，共提交 {len(report.submitted_names)} 篇"
                    )
                    messagebox.showinfo(
                        "发布完成",
                        f"已连续提交 {len(report.submitted_names)} 篇短故事。"
                        + (
                            f"\n已跳过后台已发布的 {len(report.skipped_names)} 篇。"
                            if report.skipped_names
                            else ""
                        ),
                        parent=self._root,
                    )
                else:
                    self._task_status_var.set("短故事后台已是最新状态")
            elif report.requires_user_action:
                self._task_status_var.set("等待在 Edge 完成设置")
                messagebox.showwarning(
                    "需要在 Edge 完成一次设置",
                    f"《{report.failed_name}》：{report.error}",
                    parent=self._root,
                )
            else:
                self._task_status_var.set("短故事发布未完成")
                messagebox.showerror(
                    "短故事发布未完成",
                    f"《{report.failed_name}》：{report.error}",
                    parent=self._root,
                )

        self._start_task("正在准备短故事队列", operation, done)

    def _refresh_books(self) -> None:
        self._books = self._service.list_books()
        self._books_list.delete(0, tk.END)
        for book in self._books:
            self._books_list.insert(tk.END, book.name)
        if self._books and self._selected_book_id is None:
            self._books_list.selection_set(0)
            self._load_book(self._books[0].book_id)

    def _on_select_book(self, _event: object) -> None:
        selection = self._books_list.curselection()
        if selection:
            self._load_book(self._books[selection[0]].book_id)

    def _load_book(self, book_id: str) -> None:
        book = self._service.get_book(book_id)
        self._selected_book_id = book_id
        self._book_name_var.set(book.name)
        self._source_var.set(str(book.source_dir))
        self._mode_var.set(book.mode.value)
        self._limit_var.set(str(book.limit))
        self._time_var.set(
            ", ".join(
                publish_time.isoformat(timespec="minutes")
                for publish_time in book.effective_publish_times
            )
        )
        self._start_date_var.set(
            book.publish_start_date.isoformat()
            if book.publish_start_date is not None
            else ""
        )
        self._chapter_start_var.set(str(book.next_chapter))
        self._chapter_end_var.set(
            str(book.publish_end_chapter)
            if book.publish_end_chapter is not None
            else ""
        )
        self._ai_generated_var.set(book.ai_generated)
        self._publish_state_var.set(
            "暂不发布" if book.publish_start_date is None else "已设置自动排程"
        )
        self._update_failure_controls(book_id)
        self._refresh_schedule()

    def _update_failure_controls(self, book_id: str) -> None:
        failure_status = getattr(self._service, "failure_status", None)
        failed_chapter, error = (
            failure_status(book_id) if callable(failure_status) else (None, None)
        )
        if failed_chapter is None or not error:
            self._failure_var.set("")
            self._failure_label.pack_forget()
            self._recovery_button.pack_forget()
            self._diagnostic_button.pack_forget()
            return
        self._failure_var.set(f"第{failed_chapter}章未完成")
        self._failure_label.pack(side="left", padx=(12, 0))
        self._recovery_button.pack(side="left", padx=(8, 0))
        self._diagnostic_button.pack(side="left", padx=(8, 0))

    def _refresh_schedule(self) -> None:
        self._schedule.delete(*self._schedule.get_children())
        self._schedule_detail.delete(*self._schedule_detail.get_children())
        self._schedule_days = {}
        self._detail_date_var.set("当天章节")
        if self._selected_book_id is None:
            return
        days = self._service.get_schedule(self._selected_book_id)
        item_ids: list[str] = []
        for index, (day, row) in enumerate(zip(days, format_schedule_rows(days), strict=True)):
            tags = [schedule_row_tag(day)]
            if index % 2:
                tags.append("alternating-row")
            item_id = self._schedule.insert(
                "",
                tk.END,
                values=row,
                tags=tuple(tags),
            )
            self._schedule_days[item_id] = day
            item_ids.append(item_id)
        if item_ids:
            self._schedule.selection_set(item_ids[0])
            self._schedule.focus(item_ids[0])
            self._show_schedule_day(item_ids[0])

    def _on_select_schedule_day(self, _event: object) -> None:
        selection = self._schedule.selection()
        if selection:
            self._show_schedule_day(selection[0])

    def _show_schedule_day(self, item_id: str) -> None:
        self._schedule_detail.delete(*self._schedule_detail.get_children())
        day = self._schedule_days.get(item_id)
        if day is None:
            self._detail_date_var.set("当天章节")
            return
        self._detail_date_var.set(format_schedule_detail_title(day))
        for index, row in enumerate(format_schedule_detail_rows(day)):
            tags = ("alternating-row",) if index % 2 else ()
            self._schedule_detail.insert("", tk.END, values=row, tags=tags)

    def _save_policy(self) -> None:
        if self._selected_book_id is None:
            return
        try:
            publish_times = parse_publish_times(self._time_var.get())
            self._service.update_policy(
                self._selected_book_id,
                mode=PublishMode(self._mode_var.get()),
                limit=int(self._limit_var.get()),
                publish_time=publish_times[0],
                publish_times=publish_times,
                publish_start_date=parse_publish_start_date(self._start_date_var.get()),
                next_chapter=int(self._chapter_start_var.get()),
                publish_end_chapter=parse_publish_end_chapter(self._chapter_end_var.get()),
                ai_generated=self._ai_generated_var.get(),
            )
        except (ValueError, KeyError) as error:
            messagebox.showerror("无法保存设置", str(error), parent=self._root)
            return
        self._load_book(self._selected_book_id)

    def _pause_publishing(self) -> None:
        self._start_date_var.set("")
        self._publish_state_var.set("暂不发布（保存后生效）")

    def _open_date_picker(self, target: tk.StringVar, parent: tk.Misc) -> None:
        try:
            selected = parse_publish_start_date(target.get()) or date.today()
        except ValueError:
            selected = date.today()
        dialog = tk.Toplevel(parent)
        dialog.title("选择首个发布日期")
        dialog.transient(parent)
        dialog.grab_set()
        year_var = tk.StringVar(value=str(selected.year))
        month_var = tk.StringVar(value=str(selected.month))
        day_var = tk.StringVar(value=str(selected.day))

        ttk.Label(dialog, text="年").grid(row=0, column=0, padx=(12, 6), pady=12)
        ttk.Combobox(
            dialog,
            textvariable=year_var,
            values=tuple(str(year) for year in range(date.today().year - 1, date.today().year + 11)),
            width=6,
        ).grid(row=0, column=1, pady=12)
        ttk.Label(dialog, text="月").grid(row=0, column=2, padx=(12, 6), pady=12)
        ttk.Spinbox(dialog, from_=1, to=12, textvariable=month_var, width=4).grid(
            row=0, column=3, pady=12
        )
        ttk.Label(dialog, text="日").grid(row=0, column=4, padx=(12, 6), pady=12)
        ttk.Spinbox(dialog, from_=1, to=31, textvariable=day_var, width=4).grid(
            row=0, column=5, padx=(0, 12), pady=12
        )

        def confirm_date() -> None:
            try:
                chosen = date(int(year_var.get()), int(month_var.get()), int(day_var.get()))
            except ValueError:
                messagebox.showerror("日期无效", "请选择真实存在的日期。", parent=dialog)
                return
            target.set(chosen.isoformat())
            dialog.destroy()

        ttk.Button(dialog, text="确定", command=confirm_date).grid(
            row=1, column=5, sticky="e", padx=(0, 12), pady=(0, 12)
        )

    def _open_add_book(self) -> None:
        dialog = tk.Toplevel(self._root)
        dialog.title("添加作品")
        dialog.transient(self._root)
        dialog.grab_set()
        values = {
            "name": tk.StringVar(),
            "source": tk.StringVar(),
            "start": tk.StringVar(value="1"),
            "mode": tk.StringVar(value=PublishMode.WORDS.value),
            "limit": tk.StringVar(),
            "time": tk.StringVar(),
            "publish_start_date": tk.StringVar(),
            "publish_end_chapter": tk.StringVar(),
            "ai_generated": tk.BooleanVar(value=True),
        }
        detected_var = tk.StringVar(value="选择项目目录后会自动识别正文和章节。")

        def choose_source() -> None:
            selected = filedialog.askdirectory(parent=dialog, title="选择正文目录")
            if not selected:
                return
            try:
                detected = discover_project(Path(selected))
            except ChapterParseError as error:
                messagebox.showerror("未识别到正文", str(error), parent=dialog)
                return
            values["source"].set(str(detected.source_dir))
            if not values["name"].get().strip():
                values["name"].set(detected.name)
            values["start"].set(str(detected.first_chapter))
            if not values["limit"].get().strip():
                values["limit"].set("10000")
            if not values["time"].get().strip():
                values["time"].set("00:00")
            detected_var.set(
                f"已识别 {detected.chapter_count} 章，正文目录：{detected.source_dir}"
            )

        def create_book() -> None:
            try:
                publish_times = parse_publish_times(values["time"].get())
                config = BookConfig(
                    book_id=uuid4().hex,
                    name=values["name"].get().strip(),
                    source_dir=Path(values["source"].get()),
                    publish_time=publish_times[0],
                    publish_times=publish_times,
                    mode=PublishMode(values["mode"].get()),
                    limit=int(values["limit"].get()),
                    next_chapter=int(values["start"].get()),
                    publish_start_date=parse_publish_start_date(
                        values["publish_start_date"].get()
                    ),
                    publish_end_chapter=parse_publish_end_chapter(
                        values["publish_end_chapter"].get()
                    ),
                    ai_generated=values["ai_generated"].get(),
                )
                self._service.add_book(config)
            except (OSError, ValueError) as error:
                messagebox.showerror("无法添加作品", str(error), parent=dialog)
                return
            dialog.destroy()
            self._selected_book_id = config.book_id
            self._refresh_books()
            self._load_book(config.book_id)

        for index, (label, key) in enumerate(
            (
                ("作品名", "name"),
                ("正文目录", "source"),
                ("起始章节", "start"),
                ("限制方式", "mode"),
                ("限制值", "limit"),
                ("发布时间（可多个）", "time"),
                ("首个发布日期（留空暂停）", "publish_start_date"),
                ("结束章节（含，留空不截止）", "publish_end_chapter"),
            )
        ):
            ttk.Label(dialog, text=label).grid(row=index, column=0, sticky="w", padx=12, pady=6)
            if key == "mode":
                ttk.Combobox(
                    dialog,
                    textvariable=values[key],
                    values=(PublishMode.WORDS.value, PublishMode.CHAPTERS.value),
                    state="readonly",
                    width=28,
                ).grid(row=index, column=1, sticky="ew", padx=12, pady=6)
            else:
                ttk.Entry(dialog, textvariable=values[key], width=32).grid(
                    row=index, column=1, sticky="ew", padx=12, pady=6
                )
        ttk.Button(dialog, text="选择目录", command=choose_source).grid(row=1, column=2, padx=(0, 12))
        ttk.Button(
            dialog,
            text="选择日期",
            command=lambda: self._open_date_picker(values["publish_start_date"], dialog),
        ).grid(row=6, column=2, padx=(0, 12))
        ttk.Checkbutton(
            dialog,
            text="AI生成：是",
            variable=values["ai_generated"],
        ).grid(row=8, column=1, sticky="w", padx=12, pady=6)
        ttk.Label(dialog, textvariable=detected_var, wraplength=420).grid(
            row=9, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 0)
        )
        ttk.Button(dialog, text="添加", command=create_book).grid(
            row=10, column=1, sticky="e", padx=12, pady=12
        )

    def _open_edge(self) -> None:
        try:
            self._gateway.launch()
        except Exception as error:
            messagebox.showerror("无法打开番茄后台", str(error), parent=self._root)
            return
        messagebox.showinfo("番茄后台", "Edge 已打开，请在其中完成登录。", parent=self._root)

    def _check_edge(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        try:
            self._gateway.launch()
            book = self._service.get_book(self._selected_book_id)
            result = self._gateway.preflight(book.name)
        except Exception as error:
            messagebox.showerror("后台检查失败", str(error), parent=self._root)
            return
        if result.status == PreflightStatus.READY:
            try:
                remote_chapters = list(self._gateway.existing_remote_chapters())
                self._service.reconcile_remote_submissions(
                    book.book_id,
                    {chapter.chapter_number for chapter in remote_chapters},
                )
                self._load_book(book.book_id)
            except Exception as error:
                messagebox.showerror("后台同步失败", str(error), parent=self._root)
                return
            messagebox.showinfo(
                "后台检查",
                f"{result.message}\n已同步 {len(remote_chapters)} 章状态。",
                parent=self._root,
            )
            return
        messagebox.showerror("后台检查未通过", result.message, parent=self._root)

    def _publish_first_day(self) -> None:
        if self._selected_book_id is None:
            messagebox.showinfo("请选择作品", "请先从左侧选择本地作品。", parent=self._root)
            return
        book = self._service.get_book(self._selected_book_id)
        if book.publish_start_date is None:
            messagebox.showinfo(
                "作品暂不发布",
                "请先设置首个发布日期并保存，之后才会生成待发布章节。",
                parent=self._root,
            )
            return
        try:
            self._gateway.launch()
            preflight = self._gateway.preflight(book.name)
        except Exception as error:
            messagebox.showerror("后台检查失败", str(error), parent=self._root)
            return
        if preflight.status != PreflightStatus.READY:
            messagebox.showerror("后台检查未通过", preflight.message, parent=self._root)
            return
        try:
            remote_chapters = list(self._gateway.existing_remote_chapters())
            self._service.reconcile_remote_submissions(
                book.book_id,
                {chapter.chapter_number for chapter in remote_chapters},
            )
            book = self._service.get_book(book.book_id)
            submitted_count = 0
            while True:
                try:
                    day = self._service.next_pending_day(book.book_id, remote_chapters)
                except ValueError as error:
                    if str(error) == "没有可提交的待发布章节":
                        break
                    raise
                drafts = [
                    PublishDraft(
                        chapter_number=chapter.number,
                        title=chapter.title,
                        body=read_chapter_body(book.source_dir, chapter),
                        publish_at=day.publish_at,
                        ai_generated=book.ai_generated,
                    )
                    for chapter in day.chapters
                ]
                token = self._service.confirm_batch(
                    book.book_id,
                    [draft.chapter_number for draft in drafts],
                )
                results = self._gateway.submit_batch(drafts, book.name)
                for result in results:
                    self._service.record_submission(
                        book.book_id,
                        result.chapter_number,
                        result.success,
                        token,
                        result.error,
                    )
                failed = next((result for result in results if not result.success), None)
                if failed is not None:
                    self._load_book(book.book_id)
                    messagebox.showerror(
                        "提交已停止",
                        f"第{failed.chapter_number}章未提交：{failed.error}",
                        parent=self._root,
                    )
                    return
                if len(results) != len(drafts):
                    raise RuntimeError("番茄后台未返回完整的提交结果")
                submitted_numbers = {
                    result.chapter_number for result in results if result.success
                }
                remote_chapters.extend(
                    RemoteChapter(
                        chapter_number=chapter.number,
                        character_count=chapter.character_count,
                        publish_at=day.publish_at,
                    )
                    for chapter in day.chapters
                    if chapter.number in submitted_numbers
                )
                submitted_count += len(submitted_numbers)
        except Exception as error:
            messagebox.showerror("提交中止", str(error), parent=self._root)
            self._refresh_schedule()
            return
        self._load_book(book.book_id)
        if submitted_count == 0:
            return
        messagebox.showinfo(
            "发布完成",
            f"已提交 {submitted_count} 章到番茄后台，未等待待发布状态。",
            parent=self._root,
        )


def run_app(data_dir: Path) -> None:
    from publisher.repository import JsonRepository

    root = tk.Tk()
    PublisherApp(
        root,
        PublishingService(JsonRepository(data_dir)),
        lambda: EdgePublisherGateway(data_dir / "fanqie-edge-profile"),
        theme_settings_path=data_dir / "ui-settings.json",
    )
    root.mainloop()
