"""All methods run on the service's single Playwright event loop."""
import asyncio
from pathlib import Path
import re
import uuid

from playwright.async_api import async_playwright
from .protocol import ToolError, require
from .store import SessionStore, DataDirectoryLease

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
                'persistent': True, 'state': 'dormant' if self.closed else 'active',
                'closed': self.closed, 'current_page_id': self.current,
                'pages': [{'page_id': k, 'url': p.url} for k, p in self.pages.items()
                          if not p.is_closed()], 'dialogs': list(self.dialogs)}


class SessionManager:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.sessions = {}
        self.profiles = set()
        self.create_lock = asyncio.Lock()
        self.locks = {}
        self.lease = DataDirectoryLease(self.root)
        self.store = None
        self.pw = None

    async def start(self):
        self.lease.acquire()
        try:
            self.store = SessionStore(self.root)
            self.pw = await async_playwright().start()
        except BaseException:
            self.lease.release()
            raise

    def record(self, sid):
        record = self.store.get(sid)
        require(record is not None, 'Unknown Session ID', 'session_not_found')
        return record

    def lock(self, sid):
        return self.locks.setdefault(sid, asyncio.Lock())

    async def activate(self, record):
        """Caller holds this identity's lock throughout launch and operation."""
        sid, profile = record['session_id'], record['profile_id']
        current = self.sessions.get(sid)
        if current and not current.closed:
            return current
        require(profile not in self.profiles, 'Profile already has an active Session', 'profile_in_use')
        self.profiles.add(profile)
        context = None
        try:
            context = await self.pw.chromium.launch_persistent_context(
                str(self.root / 'profiles' / profile),
                executable_path=str(ROOT / 'chrome-win64' / 'chrome.exe'),
                headless=record['headless'], viewport={'width': 1280, 'height': 800},
                accept_downloads=True, timeout=30000)
            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(30000)
            session = Session(sid, profile, context)
            session.lock = self.lock(sid)
            self.sessions[sid] = session

            def release_profile(*_):
                if self.sessions.get(sid) is session:
                    self.profiles.discard(profile)

            context.on('close', release_profile)
            if not session.pages:
                await context.new_page()
            return session
        except BaseException as exc:
            if context is not None:
                await context.close()
            self.sessions.pop(sid, None)
            self.profiles.discard(profile)
            if isinstance(exc, Exception):
                raise ToolError('browser_launch_failed', str(exc)) from exc
            raise

    async def create(self, options):
        require(isinstance(options, dict), 'Session options must be an object')
        require(not (set(options) - {'profile_id', 'headless'}), 'Unknown Session option')
        profile = options.get('profile_id', uuid.uuid4().hex)
        require(isinstance(profile, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', profile),
                'profile_id must contain 1..64 letters, digits, _ or -')
        headless = options.get('headless', False)
        require(type(headless) is bool, 'headless must be boolean')
        async with self.create_lock:
            record = self.store.find_profile(profile)
            fresh = record is None
            if fresh:
                record = self.store.create(uuid.uuid4().hex, profile, headless)
            sid = record['session_id']
            async with self.lock(sid):
                current = self.sessions.get(sid)
                require(not current or current.closed, 'Profile already has an active Session', 'profile_in_use')
                if 'headless' in options and headless != record['headless']:
                    self.store.set_headless(sid, headless)
                    record['headless'] = headless
                try:
                    return (await self.activate(record)).info()
                except BaseException:
                    if fresh:
                        self.store.delete(sid)
                    raise

    def get(self, sid):
        self.record(sid)
        require(sid in self.sessions, 'Session is dormant; resume it first', 'session_closed')
        session = self.sessions[sid]
        require(not session.closed, 'Browser has been closed', 'session_closed')
        return session

    async def list(self):
        result = []
        for record in self.store.list():
            s = self.sessions.get(record['session_id'])
            info = s.info() if s and not s.closed else {
                'session_id': record['session_id'], 'profile_id': record['profile_id'],
                'persistent': True, 'state': 'dormant', 'closed': True,
                'current_page_id': None, 'pages': [], 'dialogs': []}
            info.update(headless=record['headless'], created_at=record['created_at'])
            result.append(info)
        return result

    async def resume(self, sid):
        async with self.lock(sid):
            return (await self.activate(self.record(sid))).info()

    async def close_runtime(self, sid):
        s = self.sessions.get(sid)
        if s and not s.closed:
            await s.context.close()
        self.sessions.pop(sid, None)

    async def close(self, sid):
        async with self.lock(sid):
            record = self.record(sid)
            await self.close_runtime(sid)
            return {'session_id': sid, 'profile_id': record['profile_id'],
                    'closed': True, 'persistent': True, 'state': 'dormant'}

    async def forget(self, sid):
        # Use the same lock order as create: never let it cache a record while
        # we're closing its browser and about to delete that identity.
        async with self.create_lock:
            async with self.lock(sid):
                record = self.record(sid)
                await self.close_runtime(sid)
                self.store.delete(sid)
                return {'session_id': sid, 'profile_id': record['profile_id'],
                        'forgotten': True, 'profile_retained': True}

    async def shutdown(self):
        try:
            for sid in list(self.sessions):
                await self.close(sid)
            if self.pw:
                await self.pw.stop()
                self.pw = None
        finally:
            self.lease.release()

    async def action(self, sid, payload):
        from .actions import execute
        from .protocol import validate_request
        from playwright.async_api import TimeoutError as PlaywrightTimeout, Error
        request = validate_request(payload)
        async with self.lock(sid):
            s = await self.activate(self.record(sid))
            try:
                return await execute(s, request, self.root)
            except PlaywrightTimeout as exc:
                raise ToolError('timeout', str(exc)) from exc
            except Error as exc:
                code = 'session_closed' if s.closed else 'browser_error'
                raise ToolError(code, str(exc)) from exc
