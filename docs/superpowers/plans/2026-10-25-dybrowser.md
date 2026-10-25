# DyBrowser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 为 AI Agent 提供按 Session ID 持续控制本地 CfT 的 Python JSON 工具。

**Architecture:** 常驻标准库 HTTP 服务将请求提交至专用 asyncio 事件循环，Playwright 及全部浏览器对象只在该循环使用。每个 Session 一个持久化上下文及操作锁；CLI 是标准库 HTTP 客户端。

**Tech Stack:** Python 3.12、Playwright、asyncio、http.server、urllib、unittest、PowerShell。

**Spec:** docs/superpowers/specs/2026-10-25-dybrowser-design.md

## Global Constraints

- 工作目录 E:\Projects\DyBrowser；依赖安装到新建的 .venv。
- 使用 chrome-win64/chrome.exe，不下载另一份浏览器。
- HTTP 默认且仅允许回环监听；成功输出 JSON，诊断写 stderr。
- Session 内操作串行，默认操作超时 10 秒；导航默认 30 秒，覆盖范围 1–120000 毫秒。
- 密码不回传，快照输出受限并报告截断；旧快照引用不自动重定位。
- 用户数据和截图保留在项目运行目录并被忽略；测试关闭其启动的浏览器和服务。
- 目录当前无 Git 仓库，不初始化或创建提交。

## Review Focus

- 客户端发送错误 JSON、超大请求或非对象 JSON：返回结构化错误且服务继续工作，任务 1/4 测试。
- 页面导航或 DOM 重绘后使用 ref：返回 stale_reference，任务 3 测试。
- popup、手动关闭标签页/浏览器：页面列表和错误状态正确，任务 2/4 测试。
- 中文、空字符串、布尔值与数字混用、超时越界：文本完整且错误参数无副作用，任务 1/3 测试。
- 同一 profile 并发创建、多个 Session Cookie 隔离与退出恢复：配置目录锁定且可恢复，任务 2 测试。

## Task 1: 协议、安装与验证基础

**Files:** requirements.txt、setup.ps1、.gitignore、dybrowser/protocol.py、tests/test_protocol.py、tests/fixtures/index.html。

**Interfaces:** `ToolError(code: str, message: str, details: dict | None)`；`validate_request(payload: object) -> dict`；`success(data: object) -> dict`；`failure(error: Exception) -> dict`。

- [x] 写协议测试：非对象请求、未知 action、错误类型、timeout 超界被拒绝；中文与空文本保留；失败包含 ok=false、error.code。
- [x] 运行 `python -m unittest discover -s tests -v`，确认缺少协议实现导致预期失败。
- [x] 实现集中动作参数校验及 JSON 错误封装，禁止未验证参数进入浏览器操作。
- [x] 写 setup.ps1：创建 .venv、安装固定版本 Playwright、检查 CfT；依赖版本在安装时以可获得且支持 aria_snapshot 的版本固定。
- [x] 创建可点击计数按钮、中文输入框、密码框、重复按钮、下拉框、checkbox、iframe、滚动区域的本地页面。
- [x] 在 .venv 下运行协议测试通过。

## Task 2: Session 与标签页生命周期

**Files:** dybrowser/sessions.py、tests/test_sessions.py。

**Interfaces:** `SessionManager.start() -> None`、`create(options: dict) -> dict`、`list() -> list[dict]`、`close(session_id: str) -> dict`、`shutdown() -> None`（均为 async）；Session 持有 context、page_id 映射、当前页、lock 和快照引用。

- [x] 先写集成测试，断言创建返回 session_id/profile_id，独立 Session 存储隔离，已有 profile 同时打开被拒绝，关闭重开后本地站点存储恢复。
- [x] 写标签页测试：新页与 popup 可列出/切换，关闭当前页后明确选取仍存活页，手动关闭上下文后请求返回 session_closed。
- [x] 运行测试确认缺少生命周期实现导致失败。
- [x] 实现持久化上下文、随机 ID、限定在 profiles 下的 profile_id、页面登记、对话框自动 dismiss 与记录，清理异常创建结果。
- [x] 执行生命周期测试，确保 finally 清理所有测试上下文。

## Task 3: 观察、引用和浏览器动作

**Files:** dybrowser/observe.py、dybrowser/actions.py、tests/test_actions.py。

**Interfaces:** `snapshot(session, page, options: dict) -> dict`；`resolve_locator(session, page, options: dict)`；`execute(session, page, request: dict) -> dict`（均为 async）。

- [x] 先写本地浏览器测试：语义树包含按钮名称；snapshot DOM 清单含 ref；ref 点击产生计数变化；fill 中文可读取；密码值不泄漏；刷新快照或导航后旧 ref 报错。
- [x] 增加 role/text/CSS/label 唯一匹配与 nth、iframe、开放 shadow DOM、select/check/press/hover、wait、滚动、导航、evaluate 测试。
- [x] 增加 screenshot PNG 和实际坐标点击效果断言；验证截断标识和脱离 DOM 引用。
- [x] 运行测试确认所需观察/动作尚未实现。
- [x] 用 aria_snapshot 生成语义树，DOM 遍历生成元素句柄清单与边界数据；释放旧句柄，跟踪文档导航使引用失效。
- [x] 实现定位器和动作分派，输出 page_id 与必要结果；将 timeout、匹配歧义、已关闭目标转换为协议错误。
- [x] 运行全部现有测试通过。

## Task 4: 服务、CLI、使用文档与最终验收

**Files:** dybrowser.py、dybrowser/__init__.py、dybrowser/server.py、dybrowser/client.py、tests/test_service.py、examples/agent_client.py、README.md。

**Interfaces:** `Client(base_url: str).call(path: str, payload: dict | None) -> dict`；HTTP `GET /health`、`GET/POST /sessions`、`DELETE /sessions/{id}`、`POST /sessions/{id}/actions`、`POST /shutdown`。

- [x] 先写服务测试：多个独立客户端共用同一 Session 观察输入状态，非法 JSON/超大 body/未知路径返回 JSON；跨来源浏览器请求被拒绝，失败后健康检查正常；关闭释放资源。
- [x] 运行服务测试确认尚无入口/服务。
- [x] 实现专用 asyncio 工作线程、请求桥接、线程化 HTTP 接入与每 Session 锁；拒绝非本地 Host 与外部 Origin，限制请求体 1 MiB。
- [x] CLI 提供 serve、status、stop、session create/list/close、request，支持 --json/--file/stdin；绑定固定回环地址与可配置端口。
- [x] 写中文 README：安装、独立终端启动、创建 Session、stdin/文件调用、完整动作与定位参数表、错误码、iframe、ref 生命周期、持久化与截图坐标说明；提供标准库 Python Agent 示例。
- [x] 执行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` 全套测试。
- [x] 使用独立 CLI 进程完成 create → goto 本地页 → snapshot → ref click → screenshot → close → stop；检查 PNG 并核对状态变化。
- [x] 复核设计覆盖、CLI help、JSON 输出和运行产物清理，记录实际测试结果及已知边界。
