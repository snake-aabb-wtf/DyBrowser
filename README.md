# DyBrowser

**为 AI Agent 打造的本地浏览器自动化工具。**

让 Agent 打开网页、阅读页面结构、点击搜索框、输入内容、管理标签页，并在下一次运行时继续使用同一个浏览器身份。DyBrowser 使用 Python 和 Playwright 驱动 Chrome for Testing（CfT），提供 CLI、Python 客户端与本地 HTTP 接口，方便接入你的 Agent 工作流。

**创建一次 Session，长期复用同一个 ID。** Cookie 和站点数据随浏览器配置保存，正常关闭浏览器或重启服务后，Agent 仍可用原 ID 继续访问。

## 它能做什么

| 功能 | 能帮 Agent 完成什么 |
|---|---|
| 长期浏览器身份 | 不必每次从空白配置开始；保存 Cookie、localStorage 和登录数据，跨服务重启复用 Session ID |
| 读懂页面结构 | 同时获取无障碍语义树与 DOM 辅助信息，识别按钮、链接、搜索框和表单 |
| 按元素操作 | 按角色、名称、标签、文本、CSS 或快照元素引用定位，完成点击、输入、选择和按键 |
| 截图与坐标点击 | 查看实际页面画面，在常规元素定位不方便时通过视口坐标操作 |
| 多标签页 | 新建、列出、切换和关闭标签页，发现网站弹出的新窗口 |
| 多身份隔离 | 每个 Session 使用独立浏览器配置，不同 Session 的 Cookie 和站点数据互相隔离 |
| 处理复杂页面 | 支持 iframe、开放 shadow DOM、滚动、等待，以及显式执行页面 JavaScript |
| 方便程序接入 | CLI 和 HTTP 返回结构化 JSON；Python 客户端仅依赖标准库，Agent 可据错误码调整下一步 |

适合让 Agent 执行网页搜索、页面信息读取、表单填写，以及需要反复使用同一登录身份的浏览器任务。浏览器默认显示窗口，你也可以同时查看 Agent 的操作过程；需要时可启用无头模式。

## 快速开始

当前项目面向 Windows，推荐使用 Python 3.12。将 CfT 放在项目的 `chrome-win64` 目录，确保存在 `chrome-win64\chrome.exe`。

### 1. 准备环境

在 PowerShell 中进入项目目录：

```powershell
cd E:\Projects\DyBrowser
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` 会创建项目专用的 `.venv` 并安装 Playwright，不会另行下载浏览器。已经准备好环境时可跳过这一步；重复运行也不会清空浏览器身份和用户数据。

### 2. 启动服务

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py serve
```

保持这个终端运行。服务默认只监听本机 `127.0.0.1:8765`，负责持续维护浏览器；发送命令的客户端退出后，浏览器仍会保留。

### 3. 创建浏览器身份

打开另一个 PowerShell 终端，在同一项目目录执行：

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py session create
```

浏览器会启动，命令返回 JSON，其中的 `session_id` 就是 Agent 后续需要保存和携带的长期身份 ID。加上 `--headless` 可以创建无头浏览器。

### 4. 让 Agent 开始操作

支持直接通过 CLI 发送请求。下面用 JSON 文件传参，方便在 PowerShell 中处理引号和中文：

```powershell
$sid = '替换为返回的session_id'

# 打开网页
@{action='goto'; url='https://example.com'} |
    ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json

# 获取页面结构，供 Agent 选择下一步操作
@{action='snapshot'} |
    ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json

# 截图，返回本地 PNG 文件路径
@{action='screenshot'} |
    ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json
```

Agent 的典型工作方式是：**观察页面 → 选择元素 → 执行动作 → 再次观察**。完整的动作、定位参数和错误处理约定见 [AGENTS.md](AGENTS.md)。

## 接入你自己的 Agent

你可以选择适合现有工作流的接入方式：

- **CLI**：适合能执行终端命令的 Agent。保存 Session ID，生成 JSON 请求后调用 `dybrowser.py request` 即可。
- **Python 客户端**：通过 `dybrowser.client.Client` 调用，调用方只需要 Python 标准库。
- **本地 HTTP**：适合其他语言或已有工具调用框架，直接发送 JSON 请求。

仓库提供了 [Python Agent 示例](examples/agent_client.py)。服务运行时可以直接试用：

```powershell
.\.venv\Scripts\python.exe .\examples\agent_client.py --url https://example.com
```

示例会创建身份、打开网页、读取页面结构并截图，最后输出 Session ID。下次用 `--session-id 原ID` 可继续使用同一身份；加 `--close` 会在结束后关闭浏览器窗口并保留身份。

## 下次继续使用

你不必每次创建新 Session。重新启动服务后，直接使用保存的 ID 发请求，工具会按需恢复浏览器；也可以显式恢复：

```powershell
# 查看已保存的身份及运行状态
.\.venv\Scripts\python.exe .\dybrowser.py session list

# 恢复已有身份
.\.venv\Scripts\python.exe .\dybrowser.py session resume $sid

# 关闭浏览器，保留身份与用户数据
.\.venv\Scripts\python.exe .\dybrowser.py session close $sid

# 关闭服务及其维护的浏览器
.\.venv\Scripts\python.exe .\dybrowser.py stop
```

长期身份记录保存在 `state/`，浏览器用户数据保存在 `profiles/`。备份时先关闭服务，再一起保留这两个目录。若使用自定义 `--data-dir`，重启时继续使用相同目录。

需要移除某个长期 ID 时，可以执行 `session forget $sid`。它会删除身份映射并关闭浏览器，原用户数据目录仍保留。

## 你需要了解的边界

长期 Session 保留的是浏览器身份与可持久化的站点数据。登录仍可能因网站规则而过期；页面 JavaScript 内存、未提交的表单和完整标签页现场不保证跨重启恢复。Agent 恢复浏览器后，应重新获取标签页信息和页面快照。

工具主要通过无障碍语义与 DOM 操作页面，并提供截图和坐标点击补充能力。封闭 shadow DOM 等无法直接读取的页面结构，仍需结合实际画面处理。

## 文档与开发

- [AGENTS.md](AGENTS.md)：面向 AI Agent 的完整调用协议、技术规范、持久化规则、错误处理和开发验证要求。
- [examples/agent_client.py](examples/agent_client.py)：可运行的 Python 接入示例。
- `tests/`：使用本地测试页面和实际 CfT 的自动化测试。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 开源许可

本项目采用 [MIT License](LICENSE)。CfT 浏览器和第三方依赖遵循各自的许可证，不包含在本仓库中。
