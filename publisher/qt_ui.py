from datetime import date, time
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
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

from publisher.models import NovelOperation, PublishMode, ScheduledDay
from publisher.qt_theme import DEFAULT_THEME, THEMES, QtThemeStore, apply_theme


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
        self._gateway = gateway
        self._context = context
        self._theme_store = QtThemeStore(theme_settings_path)
        self._theme_name = self._theme_store.load()
        self._selected_book_id: str | None = None
        self._schedule_days: list[ScheduledDay] = []
        self.setWindowTitle("番茄创作发布助手")
        self.setMinimumSize(980, 680)
        self.resize(1180, 800)
        self._build_window()
        self._apply_theme(self._theme_name)

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
        self.pages.addWidget(self._placeholder_page("短故事发布"))
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(content, 1)
        self.navigation.currentRowChanged.connect(self._change_page)
        self.refresh_books()

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
        editor = QWidget(editor_scroll)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(14, 0, 0, 0)
        editor_layout.setSpacing(20)

        self.book_name_label = QLabel("未选择作品", editor)
        self.book_name_label.setObjectName("pageTitle")
        editor_layout.addWidget(self.book_name_label)
        self.book_source_label = QLabel("从左侧选择作品后显示正文目录和排程状态。", editor)
        self.book_source_label.setObjectName("muted")
        self.book_source_label.setWordWrap(True)
        editor_layout.addWidget(self.book_source_label)

        editor_layout.addWidget(self._policy_section(editor))
        editor_layout.addWidget(self._schedule_section(editor))
        editor_layout.addWidget(self._operation_section(editor))
        editor_layout.addStretch(1)
        editor_scroll.setWidget(editor)

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
        primary.addWidget(self.novel_operation_box)
        primary.addStretch(1)
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
        self.set_task_status("排程设置将在完整发布操作接入后保存")

    def _pause_publishing(self) -> None:
        self.start_date_edit.clear()
        self.publish_state_label.setText("暂不发布（保存后生效）")

    def _open_add_book(self) -> None:
        self.set_task_status("添加作品将在完整工作区接入后可用")

    def _on_novel_operation_changed(self, label: str) -> None:
        operation = _NOVEL_OPERATION_BY_LABEL.get(label, NovelOperation.SCHEDULED)
        self.novel_operation_button.setText(_NOVEL_OPERATION_BUTTONS[operation])

    def _start_novel_operation(self) -> None:
        self.set_task_status("发布操作将在完整工作区接入后可用")

    def set_task_status(self, text: str, *, running: bool = False) -> None:
        self.task_status_label.setText(text)
        self.task_progress.setVisible(running)

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
