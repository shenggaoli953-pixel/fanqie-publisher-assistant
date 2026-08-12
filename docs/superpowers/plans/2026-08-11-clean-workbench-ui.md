# 清爽工作台界面升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将番茄创作发布助手升级为清爽、高密度且发布状态清晰的 Tkinter 工作台，同时保持所有已验证的发布行为不变。

**Architecture:** 仅在 `publisher/ui.py` 中集中设置 ttk 视觉主题并调整现有控件的容器、间距和样式名。排程状态继续由 `ScheduledDay` 提供，新增一个纯展示标签映射函数，让 Treeview 行样式和单元测试共享同一判断规则。

**Tech Stack:** Python 3、Tkinter/ttk、unittest、PyInstaller。

## Global Constraints

- 只修改 `publisher/ui.py`、`tests/test_ui.py` 和本计划文件；不改 `publisher/browser.py`、排程、存储或数据格式。
- 不新增第三方依赖，不联网，不对番茄后台执行真实提交。
- 维持默认窗口 `1120x760` 和最小窗口 `980x680`。
- 主发布动作使用番茄橙，状态必须同时有文字和颜色。
- 项目不是 Git 仓库，不执行提交。

---

### Task 1: 让排程行的状态样式可测试

**Files:**
- Modify: `publisher/ui.py:18-45,817-833`
- Modify: `tests/test_ui.py:1-25,225-260`

**Interfaces:**
- Consumes: `ScheduledDay.status` (`pending`、`partial`、`submitted`) 和 `ScheduledDay.over_limit`。
- Produces: `schedule_row_tag(day: ScheduledDay) -> str`，返回 `"over-limit"`、`"submitted"`、`"partial"` 或 `"pending"`。

- [x] **Step 1: 编写失败测试**

```python
from publisher.ui import schedule_row_tag

def test_schedule_row_tag_gives_over_limit_precedence(self):
    day = ScheduledDay(
        publish_at=datetime(2026, 7, 27, 8, 0),
        chapters=(),
        over_limit=True,
        status="submitted",
    )

    self.assertEqual(schedule_row_tag(day), "over-limit")

def test_schedule_row_tag_matches_each_publish_state(self):
    for status in ("pending", "partial", "submitted"):
        with self.subTest(status=status):
            day = ScheduledDay(
                publish_at=datetime(2026, 7, 27, 8, 0),
                chapters=(),
                status=status,
            )
            self.assertEqual(schedule_row_tag(day), status)
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_ui.UiFormattingTests.test_schedule_row_tag_gives_over_limit_precedence tests.test_ui.UiFormattingTests.test_schedule_row_tag_matches_each_publish_state -v`  
Expected: FAIL，提示无法导入 `schedule_row_tag`。

- [x] **Step 3: 添加最小展示映射并用于 Treeview**

```python
def schedule_row_tag(day: ScheduledDay) -> str:
    if day.over_limit:
        return "over-limit"
    if day.status in {"pending", "partial", "submitted"}:
        return day.status
    return "pending"

for day, row in zip(days, format_schedule_rows(days), strict=True):
    item_id = self._schedule.insert(
        "", tk.END, values=row, tags=(schedule_row_tag(day),)
    )
    self._schedule_days[item_id] = day
    item_ids.append(item_id)
```

- [x] **Step 4: 运行状态映射和现有排程格式测试**

Run: `python -m unittest tests.test_ui -v`  
Expected: PASS，排程行状态文本格式保持不变。

### Task 2: 应用清爽工作台主题并统一两页布局

**Files:**
- Modify: `publisher/ui.py:156-472`
- Modify: `tests/test_ui.py:16-36`

**Interfaces:**
- Consumes: 现有 `PublisherApp` 的 `StringVar`、按钮实例属性和事件绑定。
- Produces: `PublisherApp._configure_styles(style: ttk.Style) -> None`，以及带 `App.*` 样式的小说和短故事页；不改变按钮命令、变量或回调名称。

- [x] **Step 1: 编写失败测试**

```python
def test_app_applies_workbench_styles_and_schedule_tags(self):
    class Service:
        def list_books(self):
            return []

    root = tk.Tk()
    root.withdraw()
    self.addCleanup(root.destroy)
    app = PublisherApp(root, Service(), object())

    self.assertEqual(app._schedule.cget("style"), "App.Treeview")
    self.assertEqual(app._schedule_detail.cget("style"), "App.Treeview")
    self.assertEqual(app._publish_button.cget("style"), "Primary.TButton")
    self.assertEqual(app._story_publish_button.cget("style"), "Primary.TButton")
    self.assertEqual(app._schedule.tag_cget("submitted", "foreground"), "#1F6B4F")
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_ui.UiFormattingTests.test_app_applies_workbench_styles_and_schedule_tags -v`  
Expected: FAIL，现有控件尚未使用 `App.Treeview` 和 `Primary.TButton`。

- [x] **Step 3: 集中配置 ttk 样式**

在 `_build_window()` 创建 `ttk.Style` 后调用以下方法，并为 Notebook、Frame、Label、Button、Entry、Combobox、Checkbutton、Labelframe、Treeview、Scrollbar、Progressbar 配置对应 `App.*` 样式。必须采用 Tkinter 自带的 `clam` 主题，因为 Windows 的 `vista` 主题会忽略按钮背景色，无法稳定呈现番茄橙主操作。

```python
def _configure_styles(self, style: ttk.Style) -> None:
    style.theme_use("clam")
    style.configure("App.TFrame", background="#F4F6F7")
    style.configure("Surface.TFrame", background="#FFFFFF")
    style.configure("App.TLabel", background="#F4F6F7", foreground="#202A2E")
    style.configure("Section.TLabel", background="#FFFFFF", foreground="#31444A",
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("Muted.TLabel", background="#FFFFFF", foreground="#718087")
    style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"),
                    foreground="#FFFFFF", background="#E86A3D", padding=(16, 8))
    style.map("Primary.TButton", background=[("active", "#D95B32"), ("disabled", "#D5DADD")])
    style.configure("Secondary.TButton", padding=(12, 7))
    style.configure("App.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF",
                    foreground="#202A2E", rowheight=31, font=("Microsoft YaHei UI", 9),
                    borderwidth=0)
    style.configure("App.Treeview.Heading", background="#E8F0F2", foreground="#31444A",
                    font=("Microsoft YaHei UI", 9, "bold"), relief="flat")
    style.map("App.Treeview", background=[("selected", "#D8EBF0")],
              foreground=[("selected", "#173E49")])
    style.configure("App.TNotebook", background="#F4F6F7", borderwidth=0)
    style.configure("App.TNotebook.Tab", padding=(20, 10), font=("Microsoft YaHei UI", 10))
    style.map("App.TNotebook.Tab", background=[("selected", "#FFFFFF")],
              foreground=[("selected", "#202A2E")])
    style.configure("Header.Horizontal.TProgressbar", troughcolor="#34434A",
                    background="#E86A3D", borderwidth=0, lightcolor="#E86A3D",
                    darkcolor="#E86A3D")
```

- [x] **Step 4: 重排已有控件并保留回调**

使用 `App.TFrame` 作为页面底色，`Surface.TFrame` 作为作品栏和右侧工作区。将小说页布局整理为作品栏、作品抬头、两个带小节标题的设置行、排程表、当天章节明细和操作区；将短故事页改用相同作品栏、标题、分隔和按钮层级。

必须保留以下命令和变量不变：

```python
command=self._open_add_book
command=self._save_policy
command=self._pause_publishing
command=self._start_open_edge
command=self._start_check_edge
command=self._start_publish_novel
command=self._save_short_story
command=self._start_publish_short_story
textvariable=self._mode_var
textvariable=self._story_name_var
```

将两个排程表声明改为：

```python
self._schedule = ttk.Treeview(..., style="App.Treeview")
self._schedule_detail = ttk.Treeview(..., style="App.Treeview")
```

并在创建后立即添加：

```python
self._schedule.tag_configure("pending", foreground="#2E7583")
self._schedule.tag_configure("partial", foreground="#9A5A00")
self._schedule.tag_configure("submitted", foreground="#1F6B4F")
self._schedule.tag_configure("over-limit", foreground="#A13B32")
```

主发布按钮必须使用：

```python
style="Primary.TButton"
```

“添加作品”“打开番茄后台”“同步后台状态”“保存并重排”“选择日期”“暂不发布”“保存设置”“在 Edge 中查看”使用：

```python
style="Secondary.TButton"
```

- [x] **Step 5: 运行 UI 测试确认通过**

Run: `python -m unittest tests.test_ui -v`  
Expected: PASS，窗口可构建，所有现有发布流程单测继续通过，新样式测试通过。

### Task 3: 执行完整回归、打包并视觉检查

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-clean-workbench-ui.md`（在执行时勾选完成项）
- Output: `release/FanqiePublisher/FanqiePublisher.exe`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的 `schedule_row_tag` 与 `App.*` ttk 样式。
- Produces: 可从桌面快捷方式启动的最新版 Windows 可执行文件。

- [x] **Step 1: 运行完整自动化测试**

Run: `python -m unittest discover -s tests -v`  
Expected: 全部 PASS；任何失败先定位并修复，再重新运行全量测试。

- [x] **Step 2: 生成发布包**

Run: `powershell -ExecutionPolicy Bypass -File .\\build.ps1`  
Expected: 退出码 `0`，生成 `release\\FanqiePublisher\\FanqiePublisher.exe`。

- [x] **Step 3: 启动并检查窗口**

Run: `Start-Process .\\release\\FanqiePublisher\\FanqiePublisher.exe`  
Expected: 窗口显示深石墨顶栏、浅色工作区、清晰的排程表与唯一橙色主发布按钮；在 `1120x760` 和 `980x680` 下无重叠或被遮挡控件。

- [x] **Step 4: 将桌面唯一快捷方式指向新包**

Run: `Get-Item 'C:\\Users\\11038\\Desktop\\番茄排程发布助手.lnk'`  
Expected: 快捷方式存在且目标为新版 `release\\FanqiePublisher\\FanqiePublisher.exe`；如构建路径未改变，不需要修改快捷方式。
