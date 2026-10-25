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

    async def test_old_closed_session_cannot_unlock_new_profile_owner(self):
        from dybrowser.protocol import ToolError
        first = await self.manager.create({})
        await self.manager.get(first['session_id']).context.close()
        new = await self.manager.create({'profile_id': first['profile_id']})
        await self.manager.close(first['session_id'])
        with self.assertRaises(ToolError) as error:
            await self.manager.create({'profile_id': first['profile_id']})
        self.assertEqual(error.exception.code, 'profile_in_use')
        self.assertFalse(self.manager.get(new['session_id']).closed)
