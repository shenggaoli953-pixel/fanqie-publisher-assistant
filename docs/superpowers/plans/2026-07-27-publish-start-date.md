# 首个发布日期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许每本书选择首个自动发布日期，或保持暂不发布。

**Architecture:** 在 `BookConfig` 中持久化可选日期；服务层据此创建或清空未提交的排程；Tkinter 界面提供日期输入和“暂不发布”状态。

**Tech Stack:** Python 3.14, dataclasses, Tkinter, unittest。

## Global Constraints

- 已提交章节的排程不被改动。
- 没有首个发布日期时不得生成或确认发布批次。
- 不新增第三方依赖。

### Task 1: 持久化和服务层

**Files:**
- Modify: `publisher/models.py`, `publisher/service.py`
- Test: `tests/test_models.py`, `tests/test_service.py`

- [ ] 先写失败测试：配置序列化保留日期；暂停时没有排程且不能确认批次。
- [ ] 用可选 `date` 保存首个发布日期，并在添加或更新策略时据此重排。
- [ ] 运行相关测试。

### Task 2: 桌面设置

**Files:**
- Modify: `publisher/ui.py`
- Test: `tests/test_ui.py`

- [ ] 显示并编辑首个发布日期，留空显示“暂不发布”。
- [ ] 添加作品默认不发布，选择日期后才建立排程。
- [ ] 运行完整测试并重新打包。
