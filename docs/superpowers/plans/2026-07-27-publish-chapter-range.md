# 可发布章节范围 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户限制自动排程只能发布指定的章节范围。

**Architecture:** `BookConfig` 持久化可选结束章节；服务层过滤扫描结果并正确推进下一章；界面显示可编辑的起始和结束章节。

**Tech Stack:** Python 3.14, dataclasses, Tkinter, unittest。

### Task 1: 范围排程

**Files:**
- Modify: `publisher/models.py`, `publisher/service.py`
- Test: `tests/test_models.py`, `tests/test_service.py`

- [ ] 为结束章节增加序列化和校验测试。
- [ ] 仅对起始至结束章节建立排程，并在提交后推进到范围内下一章。
- [ ] 运行服务层测试。

### Task 2: 范围设置界面

**Files:**
- Modify: `publisher/ui.py`
- Test: `tests/test_ui.py`

- [ ] 允许主界面和添加作品窗口编辑起始和结束章节。
- [ ] 空结束章节表示不设截止。
- [ ] 运行全量测试并重新打包。
