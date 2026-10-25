import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, fixture_server
try:
    from dybrowser.sessions import SessionManager
except ImportError:
    SessionManager = None


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(SessionManager, 'Session manager is not implemented')
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.manager = SessionManager(Path(self.temp.name))
        await self.manager.start()
        self.http, self.url = fixture_server()

    async def asyncTearDown(self):
        if hasattr(self, 'manager'):
            await self.manager.shutdown()
            self.http.shutdown()
            self.http.server_close()
            self.temp.cleanup()

    async def test_profile_isolation_lock_and_restore(self):
        from dybrowser.protocol import ToolError
        first = await self.manager.create({})
        second = await self.manager.create({})
        self.assertNotEqual(first['session_id'], second['session_id'])
        with self.assertRaises(ToolError) as error:
            await self.manager.create({'profile_id': first['profile_id']})
        self.assertEqual(error.exception.code, 'profile_in_use')
        a = self.manager.get(first['session_id'])
        b = self.manager.get(second['session_id'])
        await a.page().goto(self.url)
        await b.page().goto(self.url)
        await a.page().evaluate("localStorage.setItem('test','保留')")
        self.assertIsNone(await b.page().evaluate("localStorage.getItem('test')"))
        await a.context.add_cookies([{'name': 'persist', 'value': 'yes', 'url': self.url,
                                     'expires': 2000000000}])
        await self.manager.close(first['session_id'])
        restored = await self.manager.create({'profile_id': first['profile_id']})
        c = self.manager.get(restored['session_id'])
        await c.page().goto(self.url)
        self.assertEqual(await c.page().evaluate("localStorage.getItem('test')"), '保留')
        self.assertIn('persist', [x['name'] for x in await c.context.cookies()])

    async def test_popup_and_closed_browser(self):
        from dybrowser.protocol import ToolError
        info = await self.manager.create({})
        s = self.manager.get(info['session_id'])
        await s.page().goto(self.url)
        async with s.context.expect_page() as popup:
            await s.page().get_by_role('button', name='新窗口').click()
        p = await popup.value
        self.assertEqual(len(s.pages), 2)
        await p.close()
        self.assertEqual(len(s.pages), 1)
        await s.context.close()
        with self.assertRaises(ToolError) as error:
            self.manager.get(info['session_id'])
        self.assertEqual(error.exception.code, 'session_closed')

    async def test_closed_profile_reuses_id_and_remains_exclusive(self):
        from dybrowser.protocol import ToolError
        first = await self.manager.create({})
        await self.manager.get(first['session_id']).context.close()
        new = await self.manager.create({'profile_id': first['profile_id']})
        self.assertEqual(new['session_id'], first['session_id'])
        with self.assertRaises(ToolError) as error:
            await self.manager.create({'profile_id': first['profile_id']})
        self.assertEqual(error.exception.code, 'profile_in_use')
        self.assertFalse(self.manager.get(new['session_id']).closed)

    async def test_id_survives_manager_restart_with_cookies_and_storage(self):
        info = await self.manager.create({})
        sid = info['session_id']
        page = self.manager.get(sid).page()
        await page.goto(self.url)
        await page.evaluate("localStorage.setItem('long_term','长期数据')")
        await self.manager.get(sid).context.add_cookies([
            {'name':'long_term', 'value':'retained', 'url':self.url, 'expires':2000000000}])
        await self.manager.shutdown()
        self.manager = SessionManager(Path(self.temp.name))
        await self.manager.start()
        dormant = next(s for s in await self.manager.list() if s['session_id'] == sid)
        self.assertEqual(dormant['state'], 'dormant')
        self.assertEqual(dormant['profile_id'], info['profile_id'])
        self.assertFalse(self.manager.sessions, 'listing must not launch browsers')
        await self.manager.action(sid, {'action':'goto', 'url':self.url})
        restored = self.manager.get(sid)
        self.assertEqual(await restored.page().evaluate("localStorage.getItem('long_term')"), '长期数据')
        self.assertIn('long_term', [c['name'] for c in await restored.context.cookies()])

    async def test_close_resume_and_concurrent_first_requests_keep_identity(self):
        import asyncio
        info = await self.manager.create({})
        sid = info['session_id']
        await self.manager.close(sid)
        results = await asyncio.gather(*[
            self.manager.action(sid, {'action':'pages'}) for _ in range(3)])
        self.assertTrue(all(r['session_id'] == sid for r in results))
        self.assertEqual(len(self.manager.sessions), 1)
        await self.manager.close(sid)
        resumed = await self.manager.resume(sid)
        self.assertEqual(resumed['session_id'], sid)

    async def test_forget_removes_identity_but_keeps_profile(self):
        from dybrowser.protocol import ToolError
        info = await self.manager.create({})
        profile = Path(self.temp.name) / 'profiles' / info['profile_id']
        await self.manager.forget(info['session_id'])
        self.assertTrue(profile.exists())
        self.assertNotIn(info['session_id'], [s['session_id'] for s in await self.manager.list()])
        with self.assertRaises(ToolError) as error:
            await self.manager.action(info['session_id'], {'action':'pages'})
        self.assertEqual(error.exception.code, 'session_not_found')

    async def test_second_manager_cannot_use_same_data_directory(self):
        from dybrowser.protocol import ToolError
        second = SessionManager(Path(self.temp.name))
        try:
            with self.assertRaises(ToolError) as error:
                await second.start()
            self.assertEqual(error.exception.code, 'data_dir_in_use')
        finally:
            await second.shutdown()

    async def test_forget_racing_profile_create_does_not_return_unregistered_id(self):
        import asyncio
        info = await self.manager.create({})
        sid = info['session_id']
        await self.manager.close(sid)
        lock = self.manager.lock(sid)
        await lock.acquire()
        forgotten = asyncio.create_task(self.manager.forget(sid))
        await asyncio.sleep(0)
        created = asyncio.create_task(self.manager.create({'profile_id':info['profile_id']}))
        await asyncio.sleep(0)
        lock.release()
        try:
            _, new = await asyncio.gather(forgotten, created)
            self.assertNotEqual(new['session_id'], sid)
            self.assertIn(new['session_id'], [s['session_id'] for s in await self.manager.list()])
        finally:
            # A broken implementation may have launched a browser with no record;
            # close that orphan explicitly so the regression test cleans up too.
            for key, session in list(self.manager.sessions.items()):
                if self.manager.store.get(key) is None:
                    await session.context.close()
                    self.manager.sessions.pop(key, None)
