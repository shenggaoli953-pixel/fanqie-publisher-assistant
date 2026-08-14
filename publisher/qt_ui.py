from datetime import date, time
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from uuid import uuid4
import webbrowser

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QCheckBox,
    QComboBox,
    QDialog,
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from publisher.activity import ActivityLog, RunControl
from publisher.application import ApplicationContext
from publisher.chapters import ChapterParseError, discover_project, read_chapter_body
from publisher.diagnostics import write_diagnostic_report
from publisher.models import BookConfig, NovelOperation, PublishMode, ScheduledDay
from publisher.qt_theme import DEFAULT_THEME, THEMES, QtThemeStore, apply_theme
from publisher.short_story import (
    SHORT_STORY_EXTRA_CATEGORIES,
    SHORT_STORY_PRIMARY_CATEGORIES,
    ShortStoryConfig,
    scan_short_story_source,
    suggest_short_story_categories,
)
from publisher.updates import UpdateStatus, check_for_update
from publisher.version import APP_VERSION
from publisher.workflows import (
    NovelOperationReport,
    PublishRunReport,
    ShortStoryQueueReport,
    publish_all_scheduled,
    publish_all_short_stories,
    run_novel_operation,
    sync_novel_status,
)


_NOVEL_OPERATION_LABELS = {
    NovelOperation.SCHEDULED: "定时发布",
    NovelOperation.IMMEDIATE: "立即发布",
    NovelOperation.DRAFT: "存为草稿",
    NovelOperation.EDIT_CONTENT: "修改正文",
    NovelOperation.RESCHEDULE: "修改排期",
}
_NOVEL_OPERATION_BY_LABEL = {
    label: operation for operation, label in _NOVEL_OPERATION_LABELS.items()
}
_NOVEL_OPERATION_BUTTONS = {
    NovelOperation.SCHEDULED: "发布全部排程",
    NovelOperation.IMMEDIATE: "立即发布",
    NovelOperation.DRAFT: "存为草稿",
    NovelOperation.EDIT_CONTENT: "修改正文",
    NovelOperation.RESCHEDULE: "修改排期",
}
_STATUS_LABELS = {"pending": "待发布", "partial": "部分完成", "submitted": "已提交"}


def _parse_publish_start_date(value: str) -> date | None:
    normalized = value.strip()
    return date.fromisoformat(normalized) if normalized else None


def _parse_publish_end_chapter(value: str) -> int | None:
    normalized = value.strip()
    return int(normalized) if normalized else None


def _parse_publish_times(value: str) -> tuple[time, ...]:
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


def initial_window_size(available_width: int, available_height: int) -> tuple[int, int]:
    width = max(980, min(1180, available_width - 40))
    height = max(680, min(800, available_height - 60))
    return width, height


class PublisherWindow(QMainWindow):
    def __init__(
        self,
        service,
        gateway,
        *,
        theme_settings_path: Path | None = None,
        context=None,
    ) -> None:
        super().__init__()
        self._service = service
        self._gateway_provider = gateway
        self._gateway = gateway
        self._context = context
        self._activity_log = (
            ActivityLog(
                context.accounts.workspace_dir(context.active_profile().profile_id)
            )
            if context is not None
            else None
        )
        self._theme_store = QtThemeStore(theme_settings_path)
        self._theme_name = self._theme_store.load()
        self._selected_book_id: str | None = None
        self._selected_story_id: str | None = None
        self._schedule_days: list[ScheduledDay] = []
        self._story_extra_categories: tuple[str, ...] = ()
        self._task_events: Queue[tuple[str, object]] = Queue()
        self._task_running = False
        self._task_control: RunControl | None = None
        self._task_done_handler = lambda _result: None
        self.setWindowTitle("番茄创作发布助手")
        self.setMinimumSize(980, 680)
        self.resize(1180, 800)
        self._build_window()
        self._apply_theme(self._theme_name)
        self._refresh_accounts()
        self._task_timer = QTimer(self)
        self._task_timer.timeout.connect(self._drain_task_events)
        self._task_timer.start(100)

    def _build_window(self) -> None:
        workspace = QWidget(self)
        workspace.setObjectName("workspace")
        self.setCentralWidget(workspace)
        root_layout = QVBoxLayout(workspace)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame(workspace)
        header.setObjectName("header")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 12, 18, 12)
        header_layout.setSpacing(12)
        brand = QLabel("番茄创作发布助手", header)
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        self.page_title_label = QLabel("小说排程", header)
        self.page_title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.page_title_label)
        header_layout.addStretch(1)
        self.task_status_label = QLabel("就绪", header)
        self.task_status_label.setObjectName("taskStatus")
        self.task_status_label.setMinimumWidth(0)
        self.task_status_label.setMaximumWidth(240)
        self.task_status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addWidget(self.task_status_label, 1)
        self.task_progress = QProgressBar(header)
        self.task_progress.setRange(0, 0)
        self.task_progress.setFixedWidth(112)
        self.task_progress.setVisible(False)
        header_layout.addWidget(self.task_progress)
        self.utility_menu_button = QToolButton(header)
        self.utility_menu_button.setText("工具")
        self.utility_menu_button.setPopupMode(QToolButton.InstantPopup)
        self.utility_menu_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.utility_menu_button.setMenu(self._build_utility_menu())
        header_layout.addWidget(self.utility_menu_button)
        root_layout.addWidget(header)

        content = QFrame(workspace)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        sidebar = QFrame(content)
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(172)
        sidebar.setMaximumWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(10)
        navigation_label = QLabel("工作台", sidebar)
        navigation_label.setObjectName("muted")
        sidebar_layout.addWidget(navigation_label)
        self.navigation = QListWidget(sidebar)
        self.navigation.addItems(("小说排程", "短故事发布"))
        self.navigation.setCurrentRow(0)
        sidebar_layout.addWidget(self.navigation, 1)
        account_hint = QLabel("账号与主题在工具菜单中", sidebar)
        account_hint.setObjectName("muted")
        account_hint.setWordWrap(True)
        sidebar_layout.addWidget(account_hint)
        content_layout.addWidget(sidebar)
        self.pages = QStackedWidget(content)
        self.pages.addWidget(self._build_novel_page())
        self.pages.addWidget(self._build_short_story_page())
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(content, 1)
        self.navigation.currentRowChanged.connect(self._change_page)
        self.refresh_books()
        self.refresh_short_stories()

    def _build_utility_menu(self) -> QMenu:
        menu = QMenu(self)
        self.account_action = menu.addAction("账号管理")
        menu.addSeparator()
        themes = menu.addMenu("主题")
        for theme_name in THEMES:
            action = themes.addAction(theme_name)
            action.setCheckable(True)
            action.setChecked(theme_name == self._theme_name)
            action.triggered.connect(
                lambda checked=False, selected=theme_name: self._apply_theme(selected)
            )
        menu.addSeparator()
        self.activity_action = menu.addAction("活动记录")
        self.help_action = menu.addAction("帮助")
        self.update_action = menu.addAction("检查更新")
        self.diagnostics_action = menu.addAction("导出诊断")
        self.account_action.triggered.connect(self._open_account_manager)
        self.activity_action.triggered.connect(self._open_activity_log)
        self.help_action.triggered.connect(self._open_help)
        self.update_action.triggered.connect(self._check_for_updates)
        self.diagnostics_action.triggered.connect(self._export_diagnostics)
        return menu

    def _placeholder_page(self, title: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)
        heading = QLabel(title, page)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        subtitle = QLabel("正在载入工作区。", page)
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return page

    def _build_short_story_page(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(0)
        self.story_splitter = QSplitter(Qt.Horizontal, page)
        self.story_splitter.setChildrenCollapsible(False)

        story_panel = QFrame(self.story_splitter)
        story_layout = QVBoxLayout(story_panel)
        story_layout.setContentsMargins(0, 0, 14, 0)
        story_layout.setSpacing(10)
        story_title = QLabel("短故事", story_panel)
        story_title.setObjectName("pageTitle")
        story_layout.addWidget(story_title)
        self.story_list = QListWidget(story_panel)
        self.story_list.currentRowChanged.connect(self._on_select_story)
        story_layout.addWidget(self.story_list, 1)
        self.new_story_button = QPushButton("新建短故事", story_panel)
        self.new_story_button.clicked.connect(self._new_story)
        story_layout.addWidget(self.new_story_button)

        editor_scroll = QScrollArea(self.story_splitter)
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.NoFrame)
        self.story_editor = QWidget(editor_scroll)
        self.story_editor.setObjectName("contentPane")
        editor_layout = QVBoxLayout(self.story_editor)
        editor_layout.setContentsMargins(14, 0, 0, 0)
        editor_layout.setSpacing(20)

        heading = QLabel("短故事设置", self.story_editor)
        heading.setObjectName("pageTitle")
        editor_layout.addWidget(heading)
        editor_layout.addWidget(self._story_source_section(self.story_editor))
        editor_layout.addWidget(self._story_category_section(self.story_editor))
        editor_layout.addWidget(self._story_preview_section(self.story_editor))
        editor_layout.addWidget(self._story_operation_section(self.story_editor))
        editor_layout.addStretch(1)
        editor_scroll.setWidget(self.story_editor)

        self.story_splitter.addWidget(story_panel)
        self.story_splitter.addWidget(editor_scroll)
        self.story_splitter.setStretchFactor(0, 0)
        self.story_splitter.setStretchFactor(1, 1)
        self.story_splitter.setSizes((218, 840))
        page_layout.addWidget(self.story_splitter)
        return page

    def _story_source_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("内容与封面", section)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.story_name_edit = QLineEdit(section)
        self.story_source_edit = QLineEdit(section)
        source_row = QWidget(section)
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        source_layout.addWidget(self.story_source_edit, 1)
        source_file_button = QPushButton("文件", source_row)
        source_file_button.clicked.connect(self._choose_story_source)
        source_layout.addWidget(source_file_button)
        source_dir_button = QPushButton("目录", source_row)
        source_dir_button.clicked.connect(self._choose_story_source_directory)
        source_layout.addWidget(source_dir_button)
        self.story_cover_edit = QLineEdit(section)
        cover_row = QWidget(section)
        cover_layout = QHBoxLayout(cover_row)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        cover_layout.setSpacing(6)
        cover_layout.addWidget(self.story_cover_edit, 1)
        cover_button = QPushButton("选择封面", cover_row)
        cover_button.clicked.connect(self._choose_story_cover)
        cover_layout.addWidget(cover_button)
        self.story_ai_box = QCheckBox("AI 生成：是", section)
        self.story_consent_box = QCheckBox("已阅读并同意发布协议", section)
        form.addRow("标题", self.story_name_edit)
        form.addRow("正文来源", source_row)
        form.addRow("封面", cover_row)
        form.addRow("AI 声明", self.story_ai_box)
        form.addRow("发布协议", self.story_consent_box)
        layout.addLayout(form)
        return section

    def _story_category_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("作品分类", section)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.story_primary_category_box = QComboBox(section)
        self.story_primary_category_box.addItems(SHORT_STORY_PRIMARY_CATEGORIES)
        self.story_primary_category_box.setCurrentIndex(-1)
        form.addRow("主分类", self.story_primary_category_box)
        layout.addLayout(form)
        extra_actions = QHBoxLayout()
        self.story_extra_category_box = QComboBox(section)
        self.story_extra_category_box.addItems(SHORT_STORY_EXTRA_CATEGORIES)
        self.story_extra_category_box.setCurrentIndex(-1)
        add_extra_button = QPushButton("添加分类", section)
        add_extra_button.clicked.connect(self.add_story_extra_category)
        self.remove_extra_button = QPushButton("移除所选", section)
        self.remove_extra_button.clicked.connect(self.remove_story_extra_category)
        extra_actions.addWidget(self.story_extra_category_box, 1)
        extra_actions.addWidget(add_extra_button)
        extra_actions.addWidget(self.remove_extra_button)
        layout.addLayout(extra_actions)
        self.story_extra_count_label = QLabel("附加分类（0/7）", section)
        self.story_extra_count_label.setObjectName("muted")
        layout.addWidget(self.story_extra_count_label)
        self.story_extra_list = QListWidget(section)
        self.story_extra_list.setFixedHeight(260)
        self.story_extra_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.story_extra_list)
        return section

    def _story_preview_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("正文预览", section)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.story_preview = QPlainTextEdit(section)
        self.story_preview.setReadOnly(True)
        self.story_preview.setMinimumHeight(140)
        self.story_preview.setPlainText("选择正文文件或目录后会显示标题、字数和自动分类。")
        layout.addWidget(self.story_preview)
        return section

    def _story_operation_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.story_save_button = QPushButton("保存短故事", section)
        self.story_save_button.clicked.connect(self.save_short_story)
        self.story_open_edge_button = QPushButton("在 Edge 中查看", section)
        self.story_open_edge_button.clicked.connect(self._start_open_edge)
        self.story_publish_button = QPushButton("发布全部未发布短故事", section)
        self.story_publish_button.setProperty("primary", True)
        self.story_publish_button.clicked.connect(self._start_publish_short_stories)
        layout.addWidget(self.story_save_button)
        layout.addWidget(self.story_open_edge_button)
        layout.addStretch(1)
        layout.addWidget(self.story_publish_button)
        return section

    def refresh_short_stories(self) -> None:
        loader = getattr(self._service, "list_short_stories", None)
        self._stories = list(loader()) if callable(loader) else []
        self.story_list.blockSignals(True)
        self.story_list.clear()
        for story in self._stories:
            self.story_list.addItem(story.name)
        self.story_list.blockSignals(False)
        if self._stories and self._selected_story_id is None:
            self.story_list.setCurrentRow(0)
            self.load_short_story(self._stories[0].story_id)

    def _on_select_story(self, row: int) -> None:
        if 0 <= row < len(self._stories):
            self.load_short_story(self._stories[row].story_id)

    def load_short_story(self, story_id: str) -> None:
        getter = getattr(self._service, "get_short_story", None)
        if not callable(getter):
            return
        story = getter(story_id)
        self._selected_story_id = story_id
        self.story_name_edit.setText(story.name)
        self.story_source_edit.setText(str(story.source_path))
        self.story_cover_edit.setText(str(story.cover_path))
        self.story_primary_category_box.setCurrentText(story.primary_category)
        self.set_story_extra_categories(story.extra_categories)
        self.story_ai_box.setChecked(story.ai_generated)
        self.story_consent_box.setChecked(story.consent_confirmed)
        self.update_story_preview()

    def _new_story(self) -> None:
        self._selected_story_id = None
        self.story_list.clearSelection()
        self.story_name_edit.clear()
        self.story_source_edit.clear()
        self.story_cover_edit.clear()
        self.story_primary_category_box.setCurrentIndex(-1)
        self.story_extra_category_box.setCurrentIndex(-1)
        self.set_story_extra_categories(())
        self.story_ai_box.setChecked(True)
        self.story_consent_box.setChecked(False)
        self.story_preview.setPlainText("选择正文文件或目录后会显示标题、字数和自动分类。")

    def _choose_story_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "选择短故事正文", "", "正文文件 (*.txt *.md);;所有文件 (*.*)"
        )
        if selected:
            self.story_source_edit.setText(selected)
            self.update_story_preview()

    def _choose_story_source_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择短故事正文目录")
        if selected:
            self.story_source_edit.setText(selected)
            self.update_story_preview()

    def _choose_story_cover(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "选择短故事封面", "", "图片 (*.png *.jpg *.jpeg);;所有文件 (*.*)"
        )
        if selected:
            self.story_cover_edit.setText(selected)

    def story_extra_categories(self) -> tuple[str, ...]:
        return self._story_extra_categories

    def set_story_extra_categories(self, categories: tuple[str, ...]) -> None:
        self._story_extra_categories = tuple(
            category
            for category in dict.fromkeys(categories)
            if category in SHORT_STORY_EXTRA_CATEGORIES
        )[:7]
        self.story_extra_list.clear()
        self.story_extra_list.addItems(self._story_extra_categories)
        self.story_extra_count_label.setText(
            f"附加分类（{len(self._story_extra_categories)}/7）"
        )

    def add_story_extra_category(self) -> None:
        category = self.story_extra_category_box.currentText().strip()
        if not category:
            self.set_task_status("请选择要添加的附加分类")
            return
        if category in self._story_extra_categories:
            self.set_task_status(f"附加分类已包含：{category}")
            return
        if len(self._story_extra_categories) >= 7:
            self.set_task_status("附加分类最多选择 7 个")
            return
        self.set_story_extra_categories((*self._story_extra_categories, category))
        self.story_extra_category_box.setCurrentIndex(-1)

    def remove_story_extra_category(self) -> None:
        row = self.story_extra_list.currentRow()
        if not 0 <= row < len(self._story_extra_categories):
            self.set_task_status("请先选中要移除的附加分类")
            return
        categories = list(self._story_extra_categories)
        del categories[row]
        self.set_story_extra_categories(tuple(categories))

    def update_story_preview(self, force_category_suggestion: bool = False) -> None:
        source_text = self.story_source_edit.text().strip()
        if not source_text:
            return
        try:
            draft = scan_short_story_source(Path(source_text))
        except (OSError, ValueError) as error:
            self.story_preview.setPlainText(str(error))
            return
        if not self.story_name_edit.text().strip():
            self.story_name_edit.setText(draft.title)
        suggested_primary, suggested_extras = suggest_short_story_categories(
            draft.title, draft.body
        )
        if suggested_primary and (
            force_category_suggestion or not self.story_primary_category_box.currentText()
        ):
            self.story_primary_category_box.setCurrentText(suggested_primary)
        if suggested_extras and (
            force_category_suggestion or not self._story_extra_categories
        ):
            self.set_story_extra_categories(suggested_extras)
        category_info = "自动分类：未识别，请手动选择"
        if suggested_primary:
            category_info = f"自动分类：主分类 {suggested_primary}"
            if suggested_extras:
                category_info += f"；附加分类 {'、'.join(suggested_extras)}"
        self.story_preview.setPlainText(
            f"识别标题：{draft.title}\n"
            f"正文：{draft.character_count} 字\n"
            f"文件：{len(draft.source_files)} 个\n"
            f"{category_info}"
        )

    def save_short_story(self) -> bool:
        story_id = self._selected_story_id or uuid4().hex
        old = None
        if self._selected_story_id is not None:
            old = self._service.get_short_story(story_id)
        try:
            config = ShortStoryConfig(
                story_id=story_id,
                name=self.story_name_edit.text().strip(),
                source_path=Path(self.story_source_edit.text().strip()),
                cover_path=Path(self.story_cover_edit.text().strip()),
                primary_category=self.story_primary_category_box.currentText().strip(),
                extra_categories=self._story_extra_categories,
                ai_generated=self.story_ai_box.isChecked(),
                consent_confirmed=self.story_consent_box.isChecked(),
                remote_draft_url=old.remote_draft_url if old is not None else None,
            )
            if old is None:
                self._service.add_short_story(config)
            else:
                self._service.update_short_story(config)
        except (OSError, ValueError, KeyError) as error:
            self.set_task_status(f"无法保存短故事：{error}")
            return False
        self._selected_story_id = story_id
        self.refresh_short_stories()
        self.load_short_story(story_id)
        self.set_task_status("短故事设置已保存")
        return True

    def _start_publish_short_stories(self) -> None:
        if self._task_running:
            self.set_task_status("已有任务正在运行")
            return
        if not self.save_short_story() or self._selected_story_id is None:
            return
        control = RunControl()
        self._task_control = control

        def operation() -> ShortStoryQueueReport:
            gateway = self._make_gateway()
            try:
                return publish_all_short_stories(
                    self._service,
                    gateway,
                    on_progress=lambda message: self._task_events.put(("progress", message)),
                    control=control,
                )
            finally:
                self._close_gateway(gateway)

        def done(report: ShortStoryQueueReport) -> None:
            self.refresh_short_stories()
            if report.cancelled:
                self.set_task_status("任务已停止")
            elif report.success:
                if report.submitted_names:
                    count = len(report.submitted_names)
                    self.set_task_status(f"短故事发布完成，共提交 {count} 篇")
                    QMessageBox.information(self, "发布完成", f"已连续提交 {count} 篇短故事。")
                else:
                    self.set_task_status("短故事后台已是最新状态")
            elif report.requires_user_action:
                self.set_task_status("等待在 Edge 完成设置")
                QMessageBox.warning(
                    self,
                    "需要在 Edge 完成一次设置",
                    f"《{report.failed_name}》：{report.error}",
                )
            else:
                self.set_task_status("短故事发布未完成")
                QMessageBox.critical(
                    self,
                    "短故事发布未完成",
                    f"《{report.failed_name}》：{report.error}",
                )

        self._start_task("正在准备短故事队列", operation, done)

    def _build_novel_page(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(0)
        self.novel_splitter = QSplitter(Qt.Horizontal, page)
        self.novel_splitter.setChildrenCollapsible(False)

        book_panel = QFrame(self.novel_splitter)
        book_layout = QVBoxLayout(book_panel)
        book_layout.setContentsMargins(0, 0, 14, 0)
        book_layout.setSpacing(10)
        book_title = QLabel("作品", book_panel)
        book_title.setObjectName("pageTitle")
        book_layout.addWidget(book_title)
        self.books_list = QListWidget(book_panel)
        self.books_list.currentRowChanged.connect(self._on_select_book)
        book_layout.addWidget(self.books_list, 1)
        self.add_book_button = QPushButton("添加作品", book_panel)
        self.add_book_button.clicked.connect(self._open_add_book)
        book_layout.addWidget(self.add_book_button)

        editor_scroll = QScrollArea(self.novel_splitter)
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.NoFrame)
        self.novel_editor = QWidget(editor_scroll)
        self.novel_editor.setObjectName("contentPane")
        editor_layout = QVBoxLayout(self.novel_editor)
        editor_layout.setContentsMargins(14, 0, 0, 0)
        editor_layout.setSpacing(20)

        self.book_name_label = QLabel("未选择作品", self.novel_editor)
        self.book_name_label.setObjectName("pageTitle")
        editor_layout.addWidget(self.book_name_label)
        self.book_source_label = QLabel("从左侧选择作品后显示正文目录和排程状态。", self.novel_editor)
        self.book_source_label.setObjectName("muted")
        self.book_source_label.setWordWrap(True)
        editor_layout.addWidget(self.book_source_label)

        editor_layout.addWidget(self._policy_section(self.novel_editor))
        editor_layout.addWidget(self._schedule_section(self.novel_editor))
        editor_layout.addWidget(self._operation_section(self.novel_editor))
        editor_layout.addStretch(1)
        editor_scroll.setWidget(self.novel_editor)

        self.novel_splitter.addWidget(book_panel)
        self.novel_splitter.addWidget(editor_scroll)
        self.novel_splitter.setStretchFactor(0, 0)
        self.novel_splitter.setStretchFactor(1, 1)
        self.novel_splitter.setSizes((218, 840))
        page_layout.addWidget(self.novel_splitter)
        return page

    def _policy_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QLabel("排程设置", section)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.mode_box = QComboBox(section)
        self.mode_box.addItems((PublishMode.WORDS.value, PublishMode.CHAPTERS.value))
        self.limit_edit = QLineEdit(section)
        self.time_edit = QLineEdit(section)
        self.start_date_edit = QLineEdit(section)
        self.chapter_start_edit = QLineEdit(section)
        self.chapter_end_edit = QLineEdit(section)
        self.ai_generated_box = QCheckBox("AI 生成：是", section)
        self.publish_state_label = QLabel("", section)
        self.publish_state_label.setObjectName("muted")
        form.addRow("限制方式", self.mode_box)
        form.addRow("每日限制", self.limit_edit)
        form.addRow("发布时间", self.time_edit)
        form.addRow("首个发布日期", self.start_date_edit)
        form.addRow("起始章节", self.chapter_start_edit)
        form.addRow("结束章节", self.chapter_end_edit)
        form.addRow("AI 声明", self.ai_generated_box)
        form.addRow("发布状态", self.publish_state_label)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.pause_button = QPushButton("暂停发布", section)
        self.pause_button.clicked.connect(self._pause_publishing)
        self.save_policy_button = QPushButton("保存排程设置", section)
        self.save_policy_button.clicked.connect(self.save_policy)
        actions.addWidget(self.pause_button)
        actions.addStretch(1)
        actions.addWidget(self.save_policy_button)
        layout.addLayout(actions)
        return section

    def _schedule_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QLabel("发布排程", section)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        self.schedule_table = self._table(("日期", "章节", "字数", "状态"), section)
        self.schedule_table.itemSelectionChanged.connect(self._show_selected_schedule_day)
        self.schedule_table.setMinimumHeight(190)
        layout.addWidget(self.schedule_table)
        self.schedule_detail_label = QLabel("当天章节", section)
        self.schedule_detail_label.setObjectName("pageTitle")
        layout.addWidget(self.schedule_detail_label)
        self.schedule_detail_table = self._table(("章节", "标题", "字数"), section)
        self.schedule_detail_table.setMinimumHeight(170)
        layout.addWidget(self.schedule_detail_table)
        return section

    def _operation_section(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QLabel("发布操作", section)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        tools = QHBoxLayout()
        self.open_edge_button = QPushButton("在 Edge 中查看", section)
        self.sync_button = QPushButton("同步后台状态", section)
        self.preview_button = QPushButton("查看发布清单", section)
        self.open_edge_button.clicked.connect(self._start_open_edge)
        self.sync_button.clicked.connect(self._start_check_edge)
        self.preview_button.clicked.connect(self._open_publish_preview)
        tools.addWidget(self.open_edge_button)
        tools.addWidget(self.sync_button)
        tools.addWidget(self.preview_button)
        tools.addStretch(1)
        layout.addLayout(tools)
        primary = QHBoxLayout()
        self.novel_operation_box = QComboBox(section)
        self.novel_operation_box.addItems(tuple(_NOVEL_OPERATION_BY_LABEL))
        self.novel_operation_box.currentTextChanged.connect(self._on_novel_operation_changed)
        self.novel_operation_button = QPushButton("发布全部排程", section)
        self.novel_operation_button.setProperty("primary", True)
        self.novel_operation_button.clicked.connect(self._start_novel_operation)
        self.stop_task_button = QPushButton("停止任务", section)
        self.stop_task_button.setEnabled(False)
        self.stop_task_button.clicked.connect(self._request_task_stop)
        primary.addWidget(self.novel_operation_box)
        primary.addStretch(1)
        primary.addWidget(self.stop_task_button)
        primary.addWidget(self.novel_operation_button)
        layout.addLayout(primary)
        return section

    @staticmethod
    def _table(headers: tuple[str, ...], parent: QWidget) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh_books(self) -> None:
        loader = getattr(self._service, "list_books", None)
        self._books = list(loader()) if callable(loader) else []
        self.books_list.blockSignals(True)
        self.books_list.clear()
        for book in self._books:
            self.books_list.addItem(book.name)
        self.books_list.blockSignals(False)
        if self._books and self._selected_book_id is None:
            self.books_list.setCurrentRow(0)
            self.load_book(self._books[0].book_id)

    def _on_select_book(self, row: int) -> None:
        if 0 <= row < len(self._books):
            self.load_book(self._books[row].book_id)

    def load_book(self, book_id: str) -> None:
        getter = getattr(self._service, "get_book", None)
        if not callable(getter):
            return
        book = getter(book_id)
        self._selected_book_id = book_id
        self.book_name_label.setText(book.name)
        self.book_source_label.setText(str(book.source_dir))
        self.mode_box.setCurrentText(book.mode.value)
        self.limit_edit.setText(str(book.limit))
        self.time_edit.setText(
            ", ".join(value.isoformat(timespec="minutes") for value in book.effective_publish_times)
        )
        self.start_date_edit.setText(
            book.publish_start_date.isoformat() if book.publish_start_date else ""
        )
        self.chapter_start_edit.setText(str(book.next_chapter))
        self.chapter_end_edit.setText(
            str(book.publish_end_chapter) if book.publish_end_chapter is not None else ""
        )
        self.ai_generated_box.setChecked(book.ai_generated)
        self.publish_state_label.setText(
            "暂不发布" if book.publish_start_date is None else "已设置自动排程"
        )
        self.refresh_schedule()

    def refresh_schedule(self) -> None:
        self.schedule_table.setRowCount(0)
        self.schedule_detail_table.setRowCount(0)
        self.schedule_detail_label.setText("当天章节")
        self._schedule_days = []
        if self._selected_book_id is None:
            return
        schedule_loader = getattr(self._service, "get_schedule", None)
        if not callable(schedule_loader):
            return
        self._schedule_days = list(schedule_loader(self._selected_book_id))
        for row, day in enumerate(self._schedule_days):
            self.schedule_table.insertRow(row)
            chapters = "、".join(str(chapter.number) for chapter in day.chapters)
            values = (
                day.publish_at.strftime("%Y-%m-%d %H:%M"),
                chapters,
                str(sum(chapter.character_count for chapter in day.chapters)),
                _STATUS_LABELS.get(day.status, day.status),
            )
            for column, value in enumerate(values):
                self.schedule_table.setItem(row, column, QTableWidgetItem(value))
        if self._schedule_days:
            self.schedule_table.selectRow(0)
            self._show_schedule_day(0)

    def _show_selected_schedule_day(self) -> None:
        selected = self.schedule_table.selectionModel().selectedRows()
        if selected:
            self._show_schedule_day(selected[0].row())

    def _show_schedule_day(self, row: int) -> None:
        self.schedule_detail_table.setRowCount(0)
        if not 0 <= row < len(self._schedule_days):
            self.schedule_detail_label.setText("当天章节")
            return
        day = self._schedule_days[row]
        self.schedule_detail_label.setText(
            f"{day.publish_at.strftime('%Y-%m-%d %H:%M')} · {len(day.chapters)} 章"
        )
        for detail_row, chapter in enumerate(day.chapters):
            self.schedule_detail_table.insertRow(detail_row)
            for column, value in enumerate(
                (str(chapter.number), chapter.title, str(chapter.character_count))
            ):
                self.schedule_detail_table.setItem(
                    detail_row, column, QTableWidgetItem(value)
                )

    def save_policy(self) -> None:
        if self._selected_book_id is None:
            return
        try:
            publish_times = _parse_publish_times(self.time_edit.text())
            self._service.update_policy(
                self._selected_book_id,
                mode=PublishMode(self.mode_box.currentText()),
                limit=int(self.limit_edit.text()),
                publish_time=publish_times[0],
                publish_times=publish_times,
                publish_start_date=_parse_publish_start_date(self.start_date_edit.text()),
                next_chapter=int(self.chapter_start_edit.text()),
                publish_end_chapter=_parse_publish_end_chapter(self.chapter_end_edit.text()),
                ai_generated=self.ai_generated_box.isChecked(),
            )
        except (ValueError, KeyError) as error:
            QMessageBox.critical(self, "无法保存设置", str(error))
            return
        self.load_book(self._selected_book_id)
        self.set_task_status("排程设置已保存")

    def _pause_publishing(self) -> None:
        self.start_date_edit.clear()
        self.publish_state_label.setText("暂不发布（保存后生效）")

    def _open_add_book(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("添加作品")
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name_edit = QLineEdit(dialog)
        source_edit = QLineEdit(dialog)
        source_row = QWidget(dialog)
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(source_edit, 1)
        choose_source_button = QPushButton("选择目录", source_row)
        source_layout.addWidget(choose_source_button)
        start_edit = QLineEdit("1", dialog)
        mode_box = QComboBox(dialog)
        mode_box.addItems((PublishMode.WORDS.value, PublishMode.CHAPTERS.value))
        limit_edit = QLineEdit("10000", dialog)
        time_edit = QLineEdit("00:00", dialog)
        start_date_edit = QLineEdit(dialog)
        end_edit = QLineEdit(dialog)
        ai_box = QCheckBox("AI 生成：是", dialog)
        ai_box.setChecked(True)
        detected_label = QLabel("选择项目目录后会自动识别正文和章节。", dialog)
        detected_label.setObjectName("muted")
        detected_label.setWordWrap(True)
        form.addRow("作品名", name_edit)
        form.addRow("正文目录", source_row)
        form.addRow("起始章节", start_edit)
        form.addRow("限制方式", mode_box)
        form.addRow("限制值", limit_edit)
        form.addRow("发布时间", time_edit)
        form.addRow("首个发布日期", start_date_edit)
        form.addRow("结束章节", end_edit)
        form.addRow("AI 声明", ai_box)
        layout.addLayout(form)
        layout.addWidget(detected_label)
        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消", dialog)
        create_button = QPushButton("添加作品", dialog)
        create_button.setProperty("primary", True)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(create_button)
        layout.addLayout(buttons)

        def choose_source() -> None:
            selected = QFileDialog.getExistingDirectory(dialog, "选择正文目录")
            if not selected:
                return
            try:
                detected = discover_project(Path(selected))
            except ChapterParseError as error:
                QMessageBox.critical(dialog, "未识别到正文", str(error))
                return
            source_edit.setText(str(detected.source_dir))
            if not name_edit.text().strip():
                name_edit.setText(detected.name)
            start_edit.setText(str(detected.first_chapter))
            detected_label.setText(
                f"已识别 {detected.chapter_count} 章，正文目录：{detected.source_dir}"
            )

        def create_book() -> None:
            try:
                publish_times = _parse_publish_times(time_edit.text())
                config = BookConfig(
                    book_id=uuid4().hex,
                    name=name_edit.text().strip(),
                    source_dir=Path(source_edit.text().strip()),
                    publish_time=publish_times[0],
                    publish_times=publish_times,
                    mode=PublishMode(mode_box.currentText()),
                    limit=int(limit_edit.text()),
                    next_chapter=int(start_edit.text()),
                    publish_start_date=_parse_publish_start_date(start_date_edit.text()),
                    publish_end_chapter=_parse_publish_end_chapter(end_edit.text()),
                    ai_generated=ai_box.isChecked(),
                )
                self._service.add_book(config)
            except (OSError, ValueError) as error:
                QMessageBox.critical(dialog, "无法添加作品", str(error))
                return
            self._selected_book_id = config.book_id
            dialog.accept()
            self.refresh_books()
            self.load_book(config.book_id)

        choose_source_button.clicked.connect(choose_source)
        cancel_button.clicked.connect(dialog.reject)
        create_button.clicked.connect(create_book)
        dialog.exec()

    def _on_novel_operation_changed(self, label: str) -> None:
        operation = _NOVEL_OPERATION_BY_LABEL.get(label, NovelOperation.SCHEDULED)
        self.novel_operation_button.setText(_NOVEL_OPERATION_BUTTONS[operation])

    def _start_novel_operation(self) -> None:
        operation = _NOVEL_OPERATION_BY_LABEL.get(
            self.novel_operation_box.currentText(), NovelOperation.SCHEDULED
        )
        if operation is NovelOperation.SCHEDULED:
            self._start_publish_novel()
            return
        self._start_direct_novel_operation(operation)

    def set_task_status(self, text: str, *, running: bool = False) -> None:
        self.task_status_label.setText(text)
        self.task_progress.setVisible(running)

    def _make_gateway(self):
        provider = self._gateway_provider
        return provider() if callable(provider) else provider

    @staticmethod
    def _close_gateway(gateway) -> None:
        close = getattr(gateway, "close", None)
        if callable(close):
            close()

    def _start_task(self, label: str, operation, on_done) -> None:
        if self._task_running:
            self.set_task_status("已有任务正在运行")
            return
        self._task_running = True
        self._task_done_handler = on_done
        self.set_task_status(label, running=True)
        self.set_task_controls_enabled(False)

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
                    self.set_task_status(str(payload), running=True)
                    continue
                self._task_running = False
                self._task_control = None
                self.set_task_controls_enabled(True)
                self.set_task_status("就绪")
                if event == "error":
                    self.set_task_status("任务未完成")
                    QMessageBox.critical(self, "任务未完成", str(payload))
                else:
                    self._task_done_handler(payload)
        except Empty:
            return

    def set_task_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.open_edge_button,
            self.sync_button,
            self.preview_button,
            self.novel_operation_button,
            self.novel_operation_box,
            self.story_publish_button,
            self.story_save_button,
            self.story_open_edge_button,
            self.update_action,
            self.diagnostics_action,
            self.account_action,
        ):
            widget.setEnabled(enabled)
        self.stop_task_button.setEnabled(not enabled)

    def _request_task_stop(self) -> None:
        if self._task_control is None:
            return
        self._task_control.request_stop()
        self.stop_task_button.setEnabled(False)
        self.set_task_status("将在当前章节结束后停止", running=True)

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
            lambda _result: self.set_task_status("Edge 已打开，可从任务栏随时查看"),
        )

    def _start_check_edge(self) -> None:
        if self._selected_book_id is None:
            QMessageBox.information(self, "请选择作品", "请先从左侧选择本地作品。")
            return
        book_id = self._selected_book_id

        def operation():
            gateway = self._make_gateway()
            try:
                return sync_novel_status(self._service, gateway, book_id)
            finally:
                self._close_gateway(gateway)

        def done(result) -> None:
            self.load_book(book_id)
            self.set_task_status(f"后台状态已同步，共 {result.remote_count} 章")

        self._start_task("正在读取番茄章节列表", operation, done)

    def _open_publish_preview(self) -> None:
        if self._selected_book_id is None:
            QMessageBox.information(self, "请选择作品", "请先从左侧选择本地作品。")
            return
        days = self._service.get_schedule(self._selected_book_id)
        if not days:
            QMessageBox.information(self, "暂无发布清单", "请先设置首个发布日期并保存排程。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("发布清单")
        dialog.resize(900, 520)
        layout = QVBoxLayout(dialog)
        notice = QLabel("发布前核对章节、字数、时间与状态；不会读取或显示正文。", dialog)
        notice.setObjectName("muted")
        layout.addWidget(notice)
        table = self._table(("章节", "标题", "字数", "发布时间", "状态"), dialog)
        for day in days:
            status = "超限" if day.over_limit else _STATUS_LABELS.get(day.status, day.status)
            for chapter in day.chapters:
                row = table.rowCount()
                table.insertRow(row)
                values = (
                    f"第{chapter.number}章",
                    chapter.title,
                    str(chapter.character_count),
                    day.publish_at.strftime("%Y-%m-%d %H:%M"),
                    status,
                )
                for column, value in enumerate(values):
                    table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table, 1)
        close_button = QPushButton("关闭", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.exec()

    def _start_publish_novel(self) -> None:
        if self._task_running:
            self.set_task_status("已有任务正在运行")
            return
        if self._selected_book_id is None:
            QMessageBox.information(self, "请选择作品", "请先从左侧选择本地作品。")
            return
        book_id = self._selected_book_id
        if self._service.get_book(book_id).publish_start_date is None:
            QMessageBox.information(self, "作品暂不发布", "请先设置首个发布日期并保存。")
            return
        control = RunControl()
        self._task_control = control

        def operation() -> PublishRunReport:
            gateway = self._make_gateway()
            try:
                return publish_all_scheduled(
                    self._service,
                    gateway,
                    book_id,
                    read_body=read_chapter_body,
                    control=control,
                    activity_log=self._activity_log,
                    on_progress=lambda message: self._task_events.put(("progress", message)),
                )
            finally:
                self._close_gateway(gateway)

        def done(report: PublishRunReport) -> None:
            self.load_book(book_id)
            if report.cancelled:
                self.set_task_status("任务已停止")
            elif not report.success:
                self.set_task_status("发布已停止")
                QMessageBox.critical(
                    self, "发布未完成", f"第{report.failed_chapter}章：{report.error}"
                )
            elif report.submitted_numbers:
                count = len(report.submitted_numbers)
                self.set_task_status(f"发布完成，共提交 {count} 章")
                QMessageBox.information(self, "发布完成", f"已连续提交 {count} 章。")
            else:
                self.set_task_status("后台已是最新状态")

        self._start_task("正在准备整批发布", operation, done)

    def _start_direct_novel_operation(self, operation_kind: NovelOperation) -> None:
        if self._task_running:
            self.set_task_status("已有任务正在运行")
            return
        if self._selected_book_id is None:
            QMessageBox.information(self, "请选择作品", "请先从左侧选择本地作品。")
            return
        book_id = self._selected_book_id
        control = RunControl()
        self._task_control = control
        operation_label = _NOVEL_OPERATION_LABELS[operation_kind]

        def operation() -> NovelOperationReport:
            gateway = self._make_gateway()
            try:
                return run_novel_operation(
                    self._service,
                    gateway,
                    book_id,
                    operation_kind,
                    read_body=read_chapter_body,
                    control=control,
                    activity_log=self._activity_log,
                    on_progress=lambda message: self._task_events.put(("progress", message)),
                )
            finally:
                self._close_gateway(gateway)

        def done(report: NovelOperationReport) -> None:
            self.load_book(book_id)
            if report.cancelled:
                self.set_task_status("任务已停止")
            elif not report.success:
                self.set_task_status(f"{operation_label}未完成")
                QMessageBox.critical(
                    self, "操作未完成", f"第{report.failed_chapter}章：{report.error}"
                )
            elif report.submitted_numbers:
                count = len(report.submitted_numbers)
                skipped = len(report.skipped_numbers)
                self.set_task_status(f"{operation_label}完成，共处理 {count} 章")
                QMessageBox.information(
                    self,
                    "操作完成",
                    f"已完成 {count} 章{operation_label}。"
                    + (f"\n已跳过 {skipped} 章。" if skipped else ""),
                )
            else:
                self.set_task_status("没有需要处理的章节")

        self._start_task(f"正在准备{operation_label}", operation, done)

    def _refresh_accounts(self) -> None:
        self._account_ids: dict[str, str] = {}
        if self._context is None:
            self.account_action.setText("账号管理")
            return
        profiles = self._context.accounts.profiles()
        self._account_ids = {
            profile.display_name: profile.profile_id for profile in profiles
        }
        self.account_action.setText(f"账号：{self._context.active_profile().display_name}")

    def _open_account_manager(self) -> None:
        if self._context is None:
            QMessageBox.information(self, "账号管理", "当前运行模式未加载账号管理。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("账号管理")
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        account_box = QComboBox(dialog)
        account_box.addItems(tuple(self._account_ids))
        account_box.setCurrentText(self._context.active_profile().display_name)
        layout.addWidget(account_box)
        actions = QHBoxLayout()
        add_button = QPushButton("添加账号", dialog)
        rename_button = QPushButton("重命名", dialog)
        switch_button = QPushButton("切换账号", dialog)
        switch_button.setProperty("primary", True)
        actions.addWidget(add_button)
        actions.addWidget(rename_button)
        actions.addStretch(1)
        actions.addWidget(switch_button)
        layout.addLayout(actions)

        def add_account() -> None:
            name, accepted = QInputDialog.getText(dialog, "添加账号", "本地账号名称")
            if not accepted:
                return
            try:
                profile = self._context.accounts.add(name)
            except ValueError as error:
                QMessageBox.critical(dialog, "无法添加账号", str(error))
                return
            self._switch_account(profile.profile_id)
            dialog.accept()

        def rename_account() -> None:
            current = self._context.active_profile()
            name, accepted = QInputDialog.getText(
                dialog, "重命名账号", "本地账号名称", text=current.display_name
            )
            if not accepted:
                return
            try:
                self._context.accounts.rename(current.profile_id, name)
            except ValueError as error:
                QMessageBox.critical(dialog, "无法重命名账号", str(error))
                return
            self._refresh_accounts()
            account_box.clear()
            account_box.addItems(tuple(self._account_ids))
            account_box.setCurrentText(name)

        def switch_account() -> None:
            profile_id = self._account_ids.get(account_box.currentText())
            if profile_id is None:
                return
            self._switch_account(profile_id)
            dialog.accept()

        add_button.clicked.connect(add_account)
        rename_button.clicked.connect(rename_account)
        switch_button.clicked.connect(switch_account)
        dialog.exec()

    def _switch_account(self, profile_id: str) -> None:
        if self._context is None:
            return
        if self._task_running:
            QMessageBox.information(self, "任务正在进行", "请先停止当前任务。")
            return
        profile = self._context.switch(profile_id)
        self._service = self._context.service()
        self._gateway_provider = self._context.gateway_factory()
        self._gateway = self._gateway_provider
        self._activity_log = ActivityLog(
            self._context.accounts.workspace_dir(profile.profile_id)
        )
        self._selected_book_id = None
        self._selected_story_id = None
        self.book_name_label.setText("未选择作品")
        self.book_source_label.setText("从左侧选择作品后显示正文目录和排程状态。")
        self._refresh_accounts()
        self.refresh_books()
        self.refresh_short_stories()
        self.set_task_status(f"已切换到{profile.display_name}")

    def _open_activity_log(self) -> None:
        entries = self._activity_log.recent() if self._activity_log is not None else ()
        dialog = QDialog(self)
        dialog.setWindowTitle("活动记录")
        dialog.resize(700, 420)
        layout = QVBoxLayout(dialog)
        notice = QLabel(
            "仅记录时间、操作、章节号和错误类别；不包含正文、标题、路径、账号或登录信息。",
            dialog,
        )
        notice.setObjectName("muted")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        table = self._table(("时间", "操作", "状态", "章节", "错误类别"), dialog)
        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            values = (
                entry.recorded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                entry.operation,
                entry.state,
                f"第{entry.chapter_number}章" if entry.chapter_number else "",
                entry.error_category or "",
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table, 1)
        close_button = QPushButton("关闭", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.exec()

    def _open_help(self) -> None:
        QMessageBox.information(
            self,
            "使用帮助",
            "1. 在工具菜单选择本地账号，并在对应 Edge 窗口完成登录。\n\n"
            "2. 添加作品后核对排程；可选择定时、立即、草稿、改正文或改排期。\n\n"
            "3. 每项任务只读取一次后台章节状态；停止会在当前章节结束后生效。\n\n"
            "4. 登录、验证码、额度、平台风险或不明确的页面会停止，需在 Edge 中处理。\n\n"
            f"当前版本：{APP_VERSION}",
        )

    def _check_for_updates(self) -> None:
        self._start_task(
            "正在检查更新", lambda: check_for_update(APP_VERSION), self._show_update_result
        )

    def _show_update_result(self, report) -> None:
        if report.status is UpdateStatus.AVAILABLE:
            answer = QMessageBox.question(
                self,
                "发现新版本",
                f"当前版本：v{report.current_version}\n最新版本：v{report.latest_version}\n\n"
                "是否打开 GitHub 下载页？",
            )
            if answer == QMessageBox.Yes:
                webbrowser.open(report.release_url)
            return
        QMessageBox.information(
            self,
            "已经是最新版本",
            f"当前版本 v{report.current_version} 已是最新稳定版。",
        )

    def _export_diagnostics(self) -> None:
        if self._selected_book_id is None:
            QMessageBox.information(self, "请选择作品", "请先从左侧选择本地作品。")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "导出诊断信息",
            "fanqie-publisher-diagnostic.json",
            "JSON 文件 (*.json)",
        )
        if not destination:
            return
        try:
            report = write_diagnostic_report(
                Path(destination),
                version=APP_VERSION,
                state=self._service.get_book_state(self._selected_book_id),
                schedule=self._service.get_schedule(self._selected_book_id),
            )
        except (OSError, KeyError, ValueError) as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return
        QMessageBox.information(
            self,
            "诊断已导出",
            f"已保存诊断信息：{report.name}\n文件不包含正文、标题、路径、账号或登录信息。",
        )

    def _change_page(self, page_index: int) -> None:
        self.pages.setCurrentIndex(page_index)
        self.page_title_label.setText(("小说排程", "短故事发布")[page_index])

    def _apply_theme(self, theme_name: str) -> None:
        self._theme_name = theme_name if theme_name in THEMES else DEFAULT_THEME
        self._theme_store.save(self._theme_name)
        apply_theme(self._theme_name)
        for action in self.utility_menu_button.menu().actions():
            if action.menu() is None:
                continue
            for theme_action in action.menu().actions():
                theme_action.setChecked(theme_action.text() == self._theme_name)


def run_app(data_dir: Path) -> None:
    application = QApplication.instance() or QApplication([])
    context = ApplicationContext(data_dir)
    window = PublisherWindow(
        context.service(),
        context.gateway_factory(),
        theme_settings_path=data_dir / "ui-settings.json",
        context=context,
    )
    screen = application.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        width, height = initial_window_size(available.width(), available.height())
        window.resize(width, height)
        window.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )
    window.show()
    application.exec()
