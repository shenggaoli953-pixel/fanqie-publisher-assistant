# 短故事批量导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让用户选择一个短故事总文件夹后，按其中的自然排序批量导入全部新 TXT 正文，并保留逐篇补封面的工作流。

**Architecture:** publisher.short_story 新增无副作用的批量扫描结果，负责定位优先正文目录、自然排序、逐文件解析和异常收集。服务层将扫描结果转为本地短故事记录并一次保存，界面层只负责目录选择、显示导入结果和封面待补状态；发布队列自动跳过未准备好的条目，不启动它们的浏览器提交。

**Tech Stack:** Python 3.14, PySide6, pathlib, dataclasses, unittest, PyInstaller。

## Global Constraints

- 不限制文件数量、编号范围或编号位数；新增文件再次导入时只加入未存在的故事。
- 同一目录含有 发布顺序/源文件/*.txt 与 发布顺序/Markdown/*.md 时，只使用 源文件 下的 TXT。
- 不修改正文、封面或用户已有的短故事设置；批量导入不启动 Edge、不读取番茄后台、不发布。
- 自动分类无置信度时保留空主分类，待用户补充；封面为空的故事不可发布。
- 不提交、推送或发布版本，除非用户另外明确要求。

---

### Task 1: 批量扫描与待补封面模型

**Files:**
- Modify: publisher/short_story.py lines 227-466
- Test: tests/test_short_story.py

**Interfaces:**
- Add ShortStoryBatchCandidate(source_path, draft, primary_category, extra_categories).
- Add ShortStoryBatchScan(candidates, rejected_paths).
- Add scan_short_story_batch(root) returning ShortStoryBatchScan.
- Change ShortStoryConfig.cover_path from Path to Path or None.
- Keep ShortStoryConfig primary_category blank until publish-time validation.

- [ ] **Step 1: Write the failing scanner and readiness tests**

Create a temporary directory with 发布顺序/源文件 containing 10_十.txt, 2_二.txt and 1_一.txt, then add the same three names as Markdown files below 发布顺序/Markdown. Call scan_short_story_batch on the parent. Assert that candidates are exactly 1_一.txt, 2_二.txt, 10_十.txt, with no Markdown candidate.

Create another temporary directory with 01_有效.txt containing 正文 and 02_空白.txt containing whitespace. Assert the first candidate is retained and the empty file appears in rejected_paths. This proves an invalid file does not stop later imports.

Construct a ShortStoryConfig with cover_path=None and primary_category="". Assert validate_short_story_config raises 请先上传封面. Construct it again with a real temporary cover and blank category. Assert the validation raises 请先选择主分类.

- [ ] **Step 2: Run the targeted tests and verify red state**

Run:
    python -m unittest tests.test_short_story.ShortStoryTests.test_batch_scan_prefers_unbounded_source_txt_order_over_markdown_copies tests.test_short_story.ShortStoryTests.test_batch_scan_keeps_reading_after_one_invalid_file tests.test_short_story.ShortStoryTests.test_validation_requires_cover_and_primary_category_only_when_publishing -v

Expected: FAIL because scan_short_story_batch is not defined and nullable cover support is absent.

- [ ] **Step 3: Implement the minimum domain behavior**

Add frozen dataclasses for each candidate and scan report. scan_short_story_batch must call _batch_source_root first, scan each supported file in the returned directory using the existing natural order, call scan_short_story_source for every file, collect parse errors as rejected paths, and call suggest_short_story_categories for each valid draft.

Implement _batch_source_root with this exact precedence:
1. root/发布顺序/源文件 when that directory exists.
2. root/源文件 when that directory exists.
3. root itself.

Do not add a count limit. Existing _scan_supported_files performs the natural sort and therefore keeps 1 before 2 before 10 for every future collection size.

Serialize a missing cover as an empty string. Deserialization must turn a missing or empty persisted cover back into None while retaining all old nonempty cover paths. Remove the constructor restriction that rejects an empty primary category. validate_short_story_config must validate source first, then missing cover, then empty primary category, then existing cover file.

- [ ] **Step 4: Run the full short-story model suite**

Run:
    python -m unittest tests.test_short_story -v

Expected: PASS, including the existing single-file, Markdown and directory-merge tests.

### Task 2: 服务层增量导入与未就绪队列跳过

**Files:**
- Modify: publisher/service.py lines 1-94
- Modify: publisher/workflows.py lines 58-76 and 579-618
- Test: tests/test_service.py
- Test: tests/test_workflows.py

**Interfaces:**
- Add ShortStoryImportReport(imported_names, skipped_names, rejected_paths).
- Add PublishingService.import_short_story_folder(root).
- Add pending_setup_names to ShortStoryQueueReport with default empty tuple.

- [ ] **Step 1: Write failing service and workflow tests**

Use a temporary root/发布顺序/源文件 containing 01_先导入.txt and 02_后导入.txt. Call service.import_short_story_folder twice. Assert the first report imports both names in that order, the second report imports none and skips both, and service.list_short_stories contains only two records in the original order.

Build a short-story queue containing a first record with cover_path=None and primary_category="", followed by a ready record with a real source, cover and category. Use the existing fake publisher/gateway pattern. Assert publish_all_short_stories reports the pending name in pending_setup_names and still submits the ready record.

- [ ] **Step 2: Run the targeted tests and verify red state**

Run:
    python -m unittest tests.test_service.ServiceTests.test_import_short_story_folder_adds_only_new_txt_sources_in_order tests.test_workflows.WorkflowTests.test_short_story_queue_skips_stories_waiting_for_cover_or_category -v

Expected: FAIL because the import service method and pending_setup_names report field are missing.

- [ ] **Step 3: Implement atomic incremental import**

Import scan_short_story_batch and suggest_short_story_categories through the domain module. In PublishingService.import_short_story_folder:
1. Load the scan and all stored stories.
2. Form a source-path set using resolved paths and a casefolded title set.
3. For each candidate in scan order, skip only if its resolved source path or title is already known.
4. For a new candidate, create ShortStoryConfig with a new random story_id, the candidate title, source path, cover_path=None, detected categories, ai_generated=True and consent_confirmed=False.
5. Save the full list once only when there are new records.
6. Return imported names, skipped names and scan rejected paths.

The queue loop must test cover_path and primary_category before invoking publish_short_story. If either is missing, append the title to pending_setup_names and continue. Keep the current remote-published skip, user stop handling and first real submit failure behavior unchanged.

- [ ] **Step 4: Run service and workflow suites**

Run:
    python -m unittest tests.test_service tests.test_workflows -v

Expected: PASS, including existing queue order and remote-title tests.

### Task 3: 短故事工作台批量导入入口

**Files:**
- Modify: publisher/qt_ui.py lines 306-525 and 647-721
- Test: tests/test_qt_ui.py

**Interfaces:**
- Add PublisherWindow.import_story_folder_button.
- Add PublisherWindow._import_short_story_folder().
- Consume PublishingService.import_short_story_folder(root).

- [ ] **Step 1: Write failing Qt UI tests**

Instantiate PublisherWindow with the existing fake service and assert import_story_folder_button.text() equals 批量导入文件夹.

Create a fake service returning one ShortStoryConfig with cover_path=None. Instantiate the window and assert the first story list row reads 待补封面（待上传封面）. Assert loading that story leaves the cover editor text blank and has the placeholder 待上传封面.

- [ ] **Step 2: Run the targeted UI tests and verify red state**

Run:
    python -m unittest tests.test_qt_ui.QtUiTests.test_short_story_page_exposes_batch_import_button tests.test_qt_ui.QtUiTests.test_short_story_list_marks_entries_without_a_cover -v

Expected: FAIL because the button attribute and pending-cover presentation do not exist.

- [ ] **Step 3: Implement the UI flow**

Place a button labelled 批量导入文件夹 beneath 新建短故事 in the left short-story panel. Connect it to _import_short_story_folder.

_import_short_story_folder must open QFileDialog.getExistingDirectory with the title 选择短故事总文件夹. When cancelled, return without state changes. Otherwise call service.import_short_story_folder(Path(selected)), clear selected_story_id, refresh the story list and show one summary dialog:
已导入 N 篇；已跳过 N 篇；无法读取 N 篇。
Handle OSError and ValueError with one critical dialog titled 批量导入失败.

In refresh_short_stories, append （待上传封面） only when cover_path is None. In load_short_story, use an empty editor value and placeholder 待上传封面 for None. In save_short_story, turn an empty editor field into None rather than Path(""). Leave manual single-file and source-directory selection behavior intact.

In the final publish callback, describe pending_setup_names as 待补充设置 N 篇, without converting the queue into a failure dialog.

- [ ] **Step 4: Run all Qt UI tests in offscreen mode**

Run:
    python -m unittest tests.test_qt_ui -v

Expected: PASS with no visible desktop window.

### Task 4: 用户文档、完整回归与发行准备

**Files:**
- Modify: README.md lines 24-30 and 54-58
- Modify: CHANGELOG.md lines 1-5
- Modify: publisher/version.py line 1
- Modify: tests/test_main.py
- Test: all tests in tests/

**Interfaces:**
- Version 0.5.8 documents unlimited incremental short-story imports, TXT priority and manual cover completion.

- [ ] **Step 1: Write a failing README coverage test**

In tests/test_main.py, read the repository README using Path(__file__).parents[1] and assert it contains 批量导入 and 待上传封面.

- [ ] **Step 2: Run the test and verify red state**

Run:
    python -m unittest tests.test_main.MainTests.test_readme_describes_batch_short_story_import -v

Expected: FAIL because the README does not yet describe the new workflow.

- [ ] **Step 3: Update user-facing release text**

Set APP_VERSION to 0.5.8. Add a top CHANGELOG section that documents unlimited TXT-priority imports, duplicate source skipping and pending-cover queue exclusion. Update README short-story instructions: select a folder, import every new story in natural order, supplement covers, then publish; importing itself does not open Edge or submit a story.

- [ ] **Step 4: Run regression, real-directory scan and packaging verification**

Run:
    python -m unittest discover -s tests -v

Expected: full suite PASS.

Run:
    python -c "from pathlib import Path; from publisher.short_story import scan_short_story_batch; result = scan_short_story_batch(Path(r'C:\Users\11038\Desktop\番茄短故事')); print(len(result.candidates), result.candidates[0].source_path.name, result.candidates[-1].source_path.name, len(result.rejected_paths))"

Expected: prints the first and last current TXT names from 发布顺序/源文件, a candidate count equal to its current contents and no content upload.

Run:
    powershell -ExecutionPolicy Bypass -File .\build.ps1

Expected: all tests pass before PyInstaller produces release\FanqiePublisher\FanqiePublisher.exe.
