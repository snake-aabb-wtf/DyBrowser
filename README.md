# DyBrowser

给 AI Agent 使用的本地 Python 浏览器工具。以 Playwright 控制本目录的 `chrome-win64/chrome.exe`。Agent 创建 Session 获得 ID，后续独立 CLI 或 HTTP 请求携带该 ID，持续操作同一个浏览器。

默认启动可见窗口。浏览器由常驻服务持有，客户端退出不会关闭浏览器。无须运行 `playwright install`。

**Session ID 长期有效并保存到磁盘。** 正常关闭/重启服务后，Agent 继续携带原 ID 发请求，工具会自动拉起该身份对应的浏览器，复用其 Cookie 和站点数据。`session list` 会列出未启动的长期身份，不会因此启动浏览器。

## 安装与启动

在 PowerShell 中进入本目录：

```powershell
cd E:\Projects\DyBrowser
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

脚本创建 `.venv` 并安装 `requirements.txt`。已验证 Python 3.12.10、Playwright 1.64.1、CfT 156.0.8078.47。

终端一运行服务，保持该进程运行：

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py serve
```

就绪后输出一行 JSON，默认监听 `127.0.0.1:8765`。终端二创建 Session：

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py status
.\.venv\Scripts\python.exe .\dybrowser.py session create
```

返回示例（真实 ID 每次不同）：

```json
{"ok":true,"data":{"session_id":"...","profile_id":"...","persistent":true,"state":"active","closed":false,"current_page_id":"...","pages":[{"page_id":"...","url":"about:blank"}],"dialogs":[]}}
```

`--headless` 可在创建 Session 时启用无头模式。CLI 端口选项放在子命令前，例如 `dybrowser.py --port 8766 session create`；服务也接受 `dybrowser.py serve --port 8766`。

## 推荐：Agent 使用 Python 客户端

客户端仅依赖 Python 标准库，调用方不必加载 Playwright。从项目目录运行：

```python
from dybrowser.client import Client

client = Client()

def data(response):
    if not response['ok']:
        raise RuntimeError(response['error'])
    return response['data']

session = data(client.create())
sid = session['session_id']
data(client.action(sid, 'goto', url='https://example.com'))
view = data(client.action(sid, 'snapshot'))
print(view['aria'])
print(view['elements'])

# Agent 根据观察结果选择元素后操作：
# element = ...
# data(client.action(sid, 'click', snapshot_id=view['snapshot_id'], ref=element['ref']))

shot = data(client.action(sid, 'screenshot'))
print(shot['path'])
# 关闭窗口仍保留 Session ID，之后可用原 sid 再次请求。
# data(client.close(sid))
```

[examples/agent_client.py](examples/agent_client.py) 是可运行示例：`python examples/agent_client.py --url https://example.com`。默认保留浏览器窗口，打印其 ID；加 `--close` 在示例结束后关闭窗口并保留身份；下次加 `--session-id 原ID` 可继续使用。

## CLI 请求与 PowerShell 中文

CLI 的成功响应只向 stdout 输出 JSON，业务失败输出 JSON 并以状态码 1 退出；`--help` 和命令语法错误由 argparse 显示帮助。响应使用 UTF-8。为避免 Windows PowerShell 的管道编码和原生命令引号差异，推荐 JSON 文件或 Python 客户端。

```powershell
$sid = '替换为创建时返回的session_id'

# 推荐方式：把对象写成 UTF-8 JSON 文件。
@{action='goto'; url='https://example.com'} | ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json

@{action='snapshot'} | ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json
```

支持 JSON 位置参数、`--json`、`--file` 或省略输入参数时读取 stdin。stdin 必须是 UTF-8；在旧版 Windows PowerShell 中先设置：

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
'{"action":"snapshot"}' | .\.venv\Scripts\python.exe .\dybrowser.py request $sid
```

## Agent 的观察与操作循环

1. 创建 Session，保存 `session_id`。有多页面时同时保存 `page_id`。
2. `goto` 后调用 `snapshot`，读取 `aria` 语义树与 `elements` DOM 清单。二者互补，清单只覆盖可操作且有布局的元素，不是一份完整 DOM。
3. 优先选择明确的 role/name、label 或当前快照的 ref，执行一个动作。
4. 页面变化后重新观察。出现 `stale_reference` 就重新获取快照；`ambiguous_locator` 则缩小条件；超时后先观察当前状态再决定重试。
5. 语义或 DOM 定位不足时截图，根据视口 CSS 像素坐标使用 `click_xy`。

服务重启或关闭浏览器后，原 `session_id` 仍有效；第一次动作请求自动恢复浏览器。也可显式调用 `session resume`/`client.resume(sid)` 获取恢复后的当前页信息。原 `page_id`、`snapshot_id` 与 ref 属于之前的浏览器运行实例，不跨重启保留：恢复后先 `pages` 或 `snapshot`，再定位操作。`session list` 返回 `state:active` 或 `state:dormant`，dormant 表示身份存在但浏览器未运行。

快照包含 `snapshot_id`、URL、标题、ARIA 文本、带 `ref` 的元素清单、frame 信息及截断标识。每个元素包含标签、显式 role、名称线索、文本、输入值（密码为 null）、ID、placeholder、href、disabled/checked、bounds、in_viewport。隐式角色以 ARIA 树为准。

`snapshot` 默认最多 200 个 DOM 元素、20000 个 ARIA 字符；通过 `max_elements`（1–1000）和 `max_chars`（100–100000）调整。DOM 遍历最多检查 20000 个节点。`truncated`、`aria_truncated`、`elements_truncated` 表示输出被限制，应缩小到 frame 或使用定位器读取目标。

同页新快照、页面或其 frame 导航、关闭页面，会使先前 ref 失效。元素脱离 DOM 也会使其失效。ref 不跨页面使用，必须同时提供原 `snapshot_id`，避免 Agent 误操作新页面上的相似节点。元素仅改变文字而仍留在 DOM 时，ref 仍指向原元素；Agent 应根据任务决定是否重新观察。

主文档和开放 shadow DOM 均可观察及定位；封闭 shadow DOM 无法通过 DOM 清单访问。iframe 需明确指定 `frame` CSS/Playwright 选择器，例如 `"frame":"iframe[title=\"子框架\"]"`，再使用相同定位方式或获取该 frame 的快照。frame 快照替换该页旧快照；frame 内元素 bounds 为该 frame 的视口坐标，不能直接传给主页面 `click_xy`。

## 动作协议

所有动作可选 `page_id`，省略时使用 Session 当前页。`timeout` 单位毫秒，范围 1–120000；常规默认 10000，导航默认 30000。`page_new`、`page_switch` 会更新当前页；popup 自动登记，通过 `pages` 发现，其出现不自动切换当前页。

| action | 参数与效果 |
|---|---|
| `goto` | 必填 `url`；可选 `wait_until`: commit/domcontentloaded/load/networkidle，默认 domcontentloaded |
| `back` / `forward` / `reload` | 导航，同样支持 wait_until |
| `snapshot` | 可选 frame、max_elements、max_chars；返回 ARIA 与 DOM 引用 |
| `inspect` | 必填定位条件；返回值、文本、属性线索和脱敏的 HTML 片段；max_chars 默认 10000 |
| `text` | 必填定位条件；返回截断后的元素可见文本 |
| `click` | 必填定位条件；可选 button=left/middle/right |
| `fill` | 必填定位条件与 text，替换文本；允许空字符串清空 |
| `type` | 必填定位条件与 text，逐字输入到当前光标位置 |
| `press` | 必填 key，如 Enter、Control+A；有定位条件时对元素按键，否则对当前页面按键 |
| `hover` | 必填定位条件 |
| `select_option` | 必填定位条件与 value，按选项 value 选择 |
| `check` / `uncheck` | 必填定位条件 |
| `wait` | 恰好一种：定位条件、url（Playwright glob）或 ms（0–10000）；元素 state=attached/detached/visible/hidden，默认 visible；ref 不支持等待 detached |
| `screenshot` | full_page 默认 false；返回 PNG 绝对路径、尺寸和视口信息 |
| `click_xy` | 必填 x/y，必须在当前主页面视口内；可选 button |
| `scroll` | 可选 x/y，为滚动增量；默认 x=0、y=600，在当前鼠标位置滚动 |
| `evaluate` | 必填 expression，可选 arg；返回 result；表达式或函数必须返回可 JSON 表示的数据 |
| `pages` | 列出页面、当前页、最近自动关闭的对话框 |
| `page_new` | 可选 url，创建并选中新标签页 |
| `page_switch` | 必填 page_id，切换当前页并前置窗口 |
| `page_close` | 关闭目标页；当前页关闭后选择剩余页，无剩余页时需 page_new |

每个请求选择一种定位方式：

```json
{"action":"click","role":"button","name":"登录"}
{"action":"fill","label":"用户名","text":"agent"}
{"action":"click","text":"继续"}
{"action":"inspect","css":"#result"}
{"action":"click","snapshot_id":"快照ID","ref":"e3"}
{"action":"fill","frame":"iframe","css":"input","text":"框架内输入"}
```

role/name、label、text 默认 `exact:true`；可显式 `exact:false`。默认必须唯一匹配，多个结果返回 ambiguous_locator；可显式 `nth:0` 使用第一个，nth 从 0 开始。fill/type 的 text 是输入内容，因此定位这两个动作需用 ref/role/label/css。

字段按动作严格校验。`name` 必须与 role 配合，`exact` 仅用于 role/label/text 定位，`nth` 不适用于 ref，`snapshot_id` 必须与 ref 配合。显式传入的 page_id、frame、css 等不能是空字符串或纯空白；省略 page_id 才会使用当前页。不支持的字段组合返回 invalid_request，不会忽略条件后执行动作。

截图保存在 `artifacts/<session_id>/`，服务不传输 base64。默认视口 1280×800、device scale factor 为 1，截图像素与 CSS 视口坐标对应；响应仍带 device_scale_factor 供调用方核对。full_page 图片包含整个文档，不能直接用其图片坐标点击视口。滚动或页面变化后应重新截图。

`evaluate` 提供页面 JavaScript 能力，示例：`{"action":"evaluate","expression":"() => document.title"}`。异步求值有超时；同步死循环可能阻塞目标页面，必要时关闭 Session 重建。截图、显式 JavaScript 和网站自身渲染的文本可能包含敏感内容，密码脱敏仅覆盖工具主动输出的密码框值与其 DOM value 属性。

## HTTP 接口

本机程序可直接调用，无须 CLI：

| Method | 路径 | Body |
|---|---|---|
| GET | `/health` | 无 |
| POST | `/sessions` | `{}` 或 `{"profile_id":"指定配置ID","headless":false}` |
| GET | `/sessions` | 无 |
| DELETE | `/sessions/{session_id}` | 无 |
| POST | `/sessions/{session_id}/resume` | `{}`，显式恢复浏览器，沿用原 ID |
| DELETE | `/sessions/{session_id}/identity` | 无，关闭浏览器并遗忘 ID 映射，保留用户数据目录 |
| POST | `/sessions/{session_id}/actions` | 动作 JSON |
| POST | `/shutdown` | `{}` |

请求体为 UTF-8 JSON，最大 1 MiB。返回 `{"ok":true,"data":...}` 或 `{"ok":false,"error":{"code":"...","message":"..."}}`。本工具面向受信任本机 Agent，不提供远程绑定；检查 Host/Origin 并拒绝外部网页跨来源调用。不同 Session 可并行；同 Session 串行。HTTP 客户端超时应大于动作 timeout，附带客户端使用 150 秒上限；客户端断开不代表浏览器动作已撤销，重试前先观察状态。

`GET /health` 的 `protocol_version` 为 2，`persistent_sessions:true`。版本 2 中 DELETE Session 的含义是关闭浏览器、保留长期 ID；显式遗忘身份使用 `/identity`。

| 错误码 | Agent 建议 |
|---|---|
| `invalid_request` / `invalid_json` | 修正参数/JSON |
| `session_not_found` | ID 未登记或已被遗忘，列出 Session 或新建身份 |
| `session_closed` | 操作期间浏览器关闭，重新发起请求或 resume |
| `page_not_found` | pages 获取有效页面或 page_new |
| `profile_in_use` | 继续使用原 Session，或创建不同配置 |
| `stale_reference` | snapshot 后重新选择 ref |
| `ambiguous_locator` | 缩小定位条件或显式 nth |
| `timeout` | 重新观察页面，确认状态后重试 |
| `browser_launch_failed` | 查看错误中的浏览器启动原因、路径或配置占用 |
| `browser_error` | 查看 Playwright 反馈并重新观察 |
| `service_unavailable` | 启动服务或核对端口 |
| `data_dir_in_use` | 同一数据目录已被另一服务使用，连接原服务或选用独立 data-dir |
| `session_store_error` | 注册表不可读写或损坏，保留 state 目录并检查具体错误；工具不会重置注册表 |
| `forbidden` / `request_too_large` / `not_found` | 修正来源、请求大小或接口路径 |
| `internal_error` | 保留错误信息，检查服务与请求 |

## 关闭与持久化

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py session list
.\.venv\Scripts\python.exe .\dybrowser.py session close $sid
.\.venv\Scripts\python.exe .\dybrowser.py stop
```

`close` 和 `stop` 只关闭浏览器，长期 ID 及用户数据仍在。重启服务后直接使用原 ID，无须再次 create：

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py serve
# 另一个终端：
.\.venv\Scripts\python.exe .\dybrowser.py session resume $sid
# 或直接发送动作，自动恢复：
@{action='snapshot'} | ConvertTo-Json | Set-Content -Encoding utf8 request.json
.\.venv\Scripts\python.exe .\dybrowser.py request $sid --file .\request.json
```

持久化文件：

- `state/sessions.sqlite3`：Session ID、profile_id、窗口模式偏好、创建时间的事务性注册表。
- `profiles/<profile_id>/`：Chrome 管理的 Cookie、localStorage 等浏览器用户数据。
- `state/service.lock`：操作系统持有的服务锁，防止两个服务同时使用同一数据目录；服务退出时自动释放。

默认数据目录就是项目目录。若通过 `serve --data-dir ...` 指定其他位置，重启时必须使用相同目录。迁移/备份时先关闭服务，将 state 和 profiles 一起保留。state、profiles 均已加入 Git 忽略规则。

`session create --profile-id 已有配置ID` 会恢复该配置原来的长期 Session ID；若它已运行则返回 profile_in_use。旧版本留下的 profile 尚无注册记录时，该命令会为它登记新的长期 ID；旧版本从未保存的临时 ID 无法追溯恢复。

显式遗忘一个长期 ID：

```powershell
.\.venv\Scripts\python.exe .\dybrowser.py session forget $sid
```

这会关闭对应浏览器并删除 ID 映射，原 ID 此后返回 session_not_found；用户数据目录仍保留。可以通过 profile_id 再次登记为新身份。Python 对应 `client.resume(sid)` 和 `client.forget(sid)`。

Cookie、localStorage 等按 Chrome 自身规则保留；网站可能使登录过期。完整页面现场、JavaScript 内存、sessionStorage、标签页 ID 和快照引用不保证恢复。headless 偏好保存在注册表中，resume/自动恢复时沿用。服务 Ctrl+C 或 stop 会关闭所持有浏览器；强制结束进程可能导致浏览器残留、配置被占用或尚未落盘的站点数据丢失，注册表会保留已完成的事务。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

使用本地 HTTP 页面和实际 CfT，测试 Session 隔离与数据恢复、同 ID 跨服务进程重启、Cookie/localStorage 持久化、并发恢复、身份遗忘、数据目录互斥、注册表损坏处理、popup、无障碍树、ref 生命周期、中文输入、iframe/shadow DOM、导航、坐标点击、截图、超时及异常请求。测试会短暂显示浏览器窗口；测试产物示例保存在 `artifacts/verification.png`。
