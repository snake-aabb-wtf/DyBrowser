# DyBrowser：供 AI Agent 使用的持久化浏览器工具

> 历史设计记录：本文描述首版实现。后续已按用户要求改为跨服务重启复用长期 Session ID；close 保留身份，动作自动恢复浏览器，forget 显式移除身份映射。当前生命周期与调用方式以项目 README 为准。

日期：2026-10-25

## 目标与约束

在 E:\Projects\DyBrowser 中实现轻量 Python 工具，供 AI Agent 通过结构化请求操控浏览器。Playwright 安装在本目录新建的 .venv 中，使用 chrome-win64/chrome.exe，不另行下载浏览器。

Agent 首先创建 Session，收到 Session ID 后，在后续独立请求中携带该 ID，继续操控同一浏览器。客户端进程退出不关闭 Session。主交互方式是无障碍树与 DOM 辅助定位，截图和坐标点击作为补充。

## 架构与生命周期

- 一个 Python 常驻服务持有 Playwright 及浏览器实例，默认只监听 127.0.0.1。
- 同一个入口脚本提供服务启动、Session 创建/列出/关闭、操作请求等 CLI；同时提供 HTTP JSON 接口，供 Agent 程序直接调用。
- 每个 Session 对应独立的有头持久化浏览器上下文和用户数据目录。Session ID 随机生成，浏览器启动成功后才返回成功响应。
- 服务存活期间，Session ID 始终指向原上下文。关闭 Session 或服务后，页面运行现场不保证恢复；用户数据目录保留 Cookie、站点存储等浏览器可持久化数据。
- 支持通过先前的配置目录标识重新创建 Session，分配新 Session ID。一个配置目录不能同时被两个 Session 使用。不得把“保留用户数据”描述为完整恢复页面现场。
- Session 内操作串行执行，不同 Session 相互独立。浏览器被手动关闭时，后续请求返回可辨识的 Session 已关闭错误。
- 正常关闭服务时关闭浏览器、释放 Playwright；用户数据保留。无须后台自动重启或开机自启。

## Agent 调用契约

- 请求、响应均为 JSON；CLI 成功输出仅包含 JSON，诊断日志写入 stderr。失败输出结构化错误并返回非零退出码。
- 成功响应包含 ok、data；失败包含 ok=false 和 error（code、message、必要的 details）。需要时附 Session ID、页面 ID。
- CLI 支持从参数、UTF-8 JSON 文件或 stdin 读取操作请求，避免 PowerShell 的 JSON 引号问题。README 优先展示文件/stdin 与 Python 客户端示例。
- 提供 Python 标准库客户端示例，不要求调用方安装 Playwright。
- 页面均具有稳定的 page_id。请求可显式指定页面；省略时使用该 Session 当前页面。新窗口和弹出窗口可通过页面列表发现。
- 操作默认超时约 10 秒，导航单独允许更长超时；允许请求在受限范围内覆盖。不得无限等待。
- 参数必须验证类型、必填项与枚举值；无效请求不产生操作。未知 Session、未知页面、定位歧义、元素过期和超时有独立错误码。

## 观察与定位

### snapshot

返回页面 URL、标题、page_id、snapshot_id、Playwright 提供的无障碍语义快照，以及一组带 ref 的可操作 DOM 元素。DOM 信息包含 role/标签、可访问名称相关属性、可见文本、输入类型/当前值（密码不回传）、必要的 DOM 属性及视口边界。默认限制文本长度和元素数量，并明确标注截断。

使用 Playwright 当前支持的 aria_snapshot 获取语义树；DOM 清单与树作为互补输出，不假装二者是完全相同的节点集合。DOM 元素引用基于元素句柄，不向目标网站注入持久标记属性。初版覆盖主文档和开放 shadow DOM；iframe 交互通过显式 frame 选择器完成，snapshot 标识并列出 frame 信息，避免把未遍历的 frame 误报为空。

Agent 可在后续请求中使用 snapshot_id + ref 定位。新快照会使旧引用失效；导航、页面关闭后同样失效。元素脱离 DOM、引用不属于该页面或快照过期时，返回错误并提示重新 snapshot，不猜测相似元素。

其他定位方式：role + name（默认精确名称）、label、文本、CSS。默认要求唯一匹配；允许显式指定 nth。click/fill 等使用 Playwright 的可操作性检查。允许通过明确的 frame 选择器进入 iframe 后使用同样的定位方式。

### DOM 辅助读取

提供 inspect/text 类操作，按定位器读取文本、必要属性和受限长度的 DOM 片段。提供显式 evaluate 操作执行 Agent 指定的页面 JavaScript 并返回可 JSON 序列化结果，作为常规定位不足时的补充。该工具面向受信任本机调用方，不是对不可信客户端开放的隔离服务。

## 初版操作范围

- Session：创建、列出、关闭，指定已有用户数据配置重新创建。
- 页面：列出、新建、切换、关闭。
- 导航：goto、back、forward、reload。
- 观察：snapshot、inspect/text、screenshot。
- 元素：click、fill、type、press、select_option、check/uncheck、hover。
- 等待：等待元素状态或文本/URL 条件；允许有上限的短暂延时。
- 视口：scroll、click_xy；截图返回绝对路径和图片尺寸，坐标单位为 CSS 视口像素。全页截图坐标不能直接当视口坐标使用，响应和文档需明确说明。
- 补充：evaluate；浏览器对话框默认 dismiss，记录最近对话框信息以避免动作挂起。

截图默认写入项目 artifacts 下按 Session 分目录的 PNG 文件，支持视口与全页截图。数据目录和截图目录加入忽略规则，避免提交登录信息和运行产物。

## 文件与依赖

- dybrowser.py：CLI 入口与 HTTP 调用。
- dybrowser/：服务、Session/页面管理、观察与操作模块，按职责小范围拆分。
- requirements.txt：经验证的 Playwright 固定版本；服务尽量使用标准库，不额外引入 Web 框架。
- setup.ps1：创建 .venv 并安装依赖，验证 CfT 路径，支持重复执行。
- README.md：中文安装、启动、Agent 调用协议、完整操作示例、错误码、持久化边界与关闭方式。
- tests/：标准库 unittest 与本地 HTML 测试页面。

服务使用标准库 HTTP server 接收请求，Playwright 的对象在专用 asyncio 事件循环中创建和访问，不跨线程直接调用 Playwright。默认仅监听回环地址；接口不提供访问任意网络地址的远程绑定配置。

## 验收标准

1. .venv 内安装 Playwright，实际启动指定 CfT。
2. 独立 CLI/HTTP 调用携带同一 Session ID，操作同一浏览器并保留页面状态。
3. 本地测试页验证语义快照、DOM 引用点击、文本输入、唯一匹配校验、过期引用处理和 iframe 定位。
4. 实际生成并检查截图，验证视口坐标点击的页面效果。
5. 验证多标签页、多个 Session 隔离，以及关闭后从同一配置恢复 Cookie/站点存储。
6. 验证错误请求、未知 ID、超时和浏览器关闭返回结构化错误；服务仍可继续处理有效请求。
7. 关闭所有测试启动的浏览器与服务，保留可重复执行的测试命令。

## 不在初版范围

不实现 MCP 服务、云端部署、浏览器反检测、完整浏览器现场跨进程恢复、任务规划或 Agent 模型集成。当前工具提供可由任何 Agent 调用的本地 JSON 协议；后续可在同一协议外增加适配器。
