"""All methods run on the service's single Playwright event loop."""
import asyncio
from pathlib import Path
import re
import uuid

from playwright.async_api import async_playwright
from .protocol import ToolError, require

ROOT = Path(__file__).resolve().parents[1]


class Session:
    def __init__(self, session_id, profile_id, context):
        self.id, self.profile_id, self.context = session_id, profile_id, context
        self.lock = asyncio.Lock()
        self.pages = {}
        self.current = None
        self.closed = False
        self.snapshots = {}
        self.dialogs = []
        context.on('page', self.register)
        context.on('close', self.on_close)
        for page in context.pages:
            self.register(page)

    def on_close(self, *_):
        self.closed = True

    def register(self, page):
        if page in self.pages.values():
            return
        pid = uuid.uuid4().hex[:12]
        self.pages[pid] = page
        if self.current is None:
            self.current = pid
        page.on('close', lambda *_: self.remove(pid))
        page.on('framenavigated', lambda frame: self.snapshots.pop(pid, None))
        page.on('dialog', self.dismiss_dialog)

    async def dismiss_dialog(self, dialog):
        self.dialogs.append({'type': dialog.type, 'message': dialog.message[:2000]})
        self.dialogs = self.dialogs[-10:]
        await dialog.dismiss()

    def remove(self, pid):
        self.pages.pop(pid, None)
        self.snapshots.pop(pid, None)
        if self.current == pid:
            self.current = next(iter(self.pages), None)

    def page(self, pid=None):
        require(not self.closed, 'Browser has been closed', 'session_closed')
        pid = pid or self.current
        require(pid in self.pages and not self.pages[pid].is_closed(),
                'Unknown or closed page; use pages/page_new', 'page_not_found')
        return self.pages[pid]

    def page_id(self, page):
        return next(k for k, p in self.pages.items() if p is page)

    def info(self):
        return {'session_id': self.id, 'profile_id': self.profile_id,
                'closed': self.closed, 'current_page_id': self.current,
                'pages': [{'page_id': k, 'url': p.url} for k, p in self.pages.items()
                          if not p.is_closed()], 'dialogs': list(self.dialogs)}


class SessionManager:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.sessions = {}
        self.profiles = set()
        self.create_lock = asyncio.Lock()
        self.pw = None

    async def start(self):
        self.pw = await async_playwright().start()

    async def create(self, options):
        require(isinstance(options, dict), 'Session options must be an object')
        require(not (set(options) - {'profile_id', 'headless'}), 'Unknown Session option')
        profile = options.get('profile_id', uuid.uuid4().hex)
        require(isinstance(profile, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', profile),
                'profile_id must contain 1..64 letters, digits, _ or -')
        headless = options.get('headless', False)
        require(type(headless) is bool, 'headless must be boolean')
        async with self.create_lock:
            require(profile not in self.profiles, 'Profile already has an active Session', 'profile_in_use')
            self.profiles.add(profile)
            try:
                context = await self.pw.chromium.launch_persistent_context(
                    str(self.root / 'profiles' / profile),
                    executable_path=str(ROOT / 'chrome-win64' / 'chrome.exe'),
                    headless=headless, viewport={'width': 1280, 'height': 800},
                    accept_downloads=True, timeout=30000)
            except Exception as exc:
                self.profiles.discard(profile)
                raise ToolError('browser_launch_failed', str(exc)) from exc
            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(30000)
            sid = uuid.uuid4().hex
            session = Session(sid, profile, context)
            context.on('close', lambda *_: self.profiles.discard(profile))
            self.sessions[sid] = session
            if not session.pages:
                await context.new_page()
            return session.info()

    def get(self, sid):
        require(sid in self.sessions, 'Unknown Session ID', 'session_not_found')
        session = self.sessions[sid]
        require(not session.closed, 'Browser has been closed', 'session_closed')
        return session

    async def list(self):
        return [s.info() for s in self.sessions.values()]

    async def close(self, sid):
        require(sid in self.sessions, 'Unknown Session ID', 'session_not_found')
        s = self.sessions[sid]
        async with s.lock:
            if not s.closed:
                await s.context.close()
            # The context's close callback releases its own profile. A retained
            # closed Session may share this profile_id with a newer Session;
            # removing the lock here would unlock that newer browser.
            self.sessions.pop(sid, None)
        return {'session_id': sid, 'profile_id': s.profile_id, 'closed': True}

    async def shutdown(self):
        for sid in list(self.sessions):
            await self.close(sid)
        if self.pw:
            await self.pw.stop()
            self.pw = None

    async def action(self, sid, payload):
        from .actions import execute
        from .protocol import validate_request
        from playwright.async_api import TimeoutError as PlaywrightTimeout, Error
        request = validate_request(payload)
        s = self.get(sid)
        async with s.lock:
            self.get(sid)
            try:
                return await execute(s, request, self.root)
            except PlaywrightTimeout as exc:
                raise ToolError('timeout', str(exc)) from exc
            except Error as exc:
                code = 'session_closed' if s.closed else 'browser_error'
                raise ToolError(code, str(exc)) from exc
