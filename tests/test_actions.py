import tempfile
import unittest
from pathlib import Path
from helpers import ROOT, fixture_server
from dybrowser.sessions import SessionManager
from dybrowser.protocol import ToolError


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.manager = SessionManager(Path(self.temp.name))
        await self.manager.start()
        self.http, self.url = fixture_server()
        self.info = await self.manager.create({})
        self.sid = self.info['session_id']
        self.page = self.manager.get(self.sid).page()
        await self.page.goto(self.url)

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.http.shutdown()
        self.http.server_close()
        self.temp.cleanup()

    async def call(self, action, **kw):
        return await self.manager.action(self.sid, {'action': action, **kw})

    async def test_snapshot_refs_and_staleness(self):
        snap = await self.call('snapshot')
        self.assertIn('计数 0', snap['aria'])
        self.assertNotIn('do-not-leak', str(snap))
        node = next(e for e in snap['elements'] if e.get('text') == '计数 0')
        await self.call('click', snapshot_id=snap['snapshot_id'], ref=node['ref'])
        self.assertEqual(await self.page.locator('#count').inner_text(), '计数 1')
        await self.call('snapshot')
        with self.assertRaises(ToolError) as error:
            await self.call('click', snapshot_id=snap['snapshot_id'], ref=node['ref'])
        self.assertEqual(error.exception.code, 'stale_reference')
        snap = await self.call('snapshot')
        node = next(e for e in snap['elements'] if e.get('text') == '计数 1')
        await self.page.locator('#count').evaluate('(e)=>e.remove()')
        with self.assertRaises(ToolError):
            await self.call('click', snapshot_id=snap['snapshot_id'], ref=node['ref'])
        snap = await self.call('snapshot')
        node = snap['elements'][0]
        await self.call('reload')
        with self.assertRaises(ToolError):
            await self.call('click', snapshot_id=snap['snapshot_id'], ref=node['ref'])

    async def test_locators_controls_and_iframe(self):
        await self.call('fill', label='姓名', text='你好 Agent')
        await self.call('type', css='#name', text='!')
        data = await self.call('inspect', css='#name')
        self.assertEqual(data['value'], '你好 Agent!')
        self.assertNotIn('do-not-leak', str(await self.call('inspect', css='body')))
        await self.call('press', css='#name', key='End')
        await self.call('hover', role='button', name='计数 0')
        with self.assertRaises(ToolError) as error:
            await self.call('click', role='button', name='重复')
        self.assertEqual(error.exception.code, 'ambiguous_locator')
        await self.call('click', role='button', name='重复', nth=1)
        await self.call('select_option', label='选择', value='b')
        self.assertEqual(await self.page.locator('select').input_value(), 'b')
        await self.call('check', label='同意')
        self.assertTrue(await self.page.get_by_label('同意').is_checked())
        await self.call('uncheck', label='同意')
        await self.call('fill', frame='iframe', label='框架输入', text='frame value')
        frame = await self.call('snapshot', frame='iframe')
        self.assertIn('框架按钮', frame['aria'])
        shadow = await self.call('snapshot')
        self.assertTrue(any(e.get('text') == 'Shadow 按钮' for e in shadow['elements']))
        self.assertTrue(shadow['frames'])
        await self.call('wait', text='计数 0', state='visible')
        await self.call('wait', url=self.url + '/')
        await self.call('wait', ms=1)
        with self.assertRaises(ToolError) as error:
            await self.call('wait', css='#missing', timeout=100)
        self.assertEqual(error.exception.code, 'timeout')

    async def test_screenshot_coordinates_evaluate_and_truncation(self):
        snap = await self.call('snapshot', max_elements=1, max_chars=100)
        self.assertTrue(snap['truncated'])
        rect = await self.page.locator('#count').bounding_box()
        await self.call('click_xy', x=rect['x'] + rect['width']/2, y=rect['y'] + rect['height']/2)
        self.assertEqual(await self.page.locator('#count').inner_text(), '计数 1')
        shot = await self.call('screenshot')
        self.assertEqual(Path(shot['path']).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(shot['width'], 1280)
        verification = ROOT / 'artifacts' / 'verification.png'
        verification.parent.mkdir(exist_ok=True)
        verification.write_bytes(Path(shot['path']).read_bytes())
        await self.call('scroll', y=400)
        self.assertGreater(await self.page.evaluate('scrollY'), 0)
        result = await self.call('evaluate', expression='(arg) => arg + 1', arg=41)
        self.assertEqual(result['result'], 42)
        await self.call('evaluate', expression="alert('hello')")
        self.assertEqual(self.manager.get(self.sid).dialogs[-1]['message'], 'hello')

    async def test_page_management_and_navigation(self):
        original = self.info['current_page_id']
        new = await self.call('page_new', url=self.url + '/popup.html')
        pages = await self.call('pages')
        self.assertEqual(len(pages['pages']), 2)
        await self.call('page_switch', page_id=original)
        await self.call('goto', url=self.url + '/popup.html')
        await self.call('back')
        self.assertEqual(self.page.url, self.url + '/')
        await self.call('forward')
        self.assertIn('popup.html', self.page.url)
        await self.call('page_close', page_id=new['page_id'])
        self.assertEqual(len((await self.call('pages'))['pages']), 1)
