import http.client as http_client
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from helpers import ROOT, fixture_server


class ServiceTests(unittest.TestCase):
    def test_independent_cli_calls_errors_and_shutdown(self):
        self.assertTrue((ROOT / 'dybrowser.py').exists(), 'Service/CLI entry is not implemented')
        # Port 0 is reserved for tests/embedding; read bound port from ready JSON.
        temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        log = open(Path(temp.name) / 'server.log', 'w', encoding='utf-8')
        proc = subprocess.Popen([sys.executable, '-u', str(ROOT / 'dybrowser.py'),
            'serve', '--port', '0', '--data-dir', temp.name],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8')
        fixture, url = fixture_server()
        port = None
        try:
            import queue
            import threading
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
            ready = json.loads(lines.get(timeout=25))
            port = ready['data']['port']

            def http(method, path, body=None, headers=None):
                c = http_client.HTTPConnection('127.0.0.1', port, timeout=140)
                try:
                    c.request(method, path, body=body, headers=headers or {})
                    response = c.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    c.close()

            def cli(*args, payload=None):
                p = subprocess.run([sys.executable, str(ROOT/'dybrowser.py'), '--port', str(port), *args],
                    input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    capture_output=True, encoding='utf-8', timeout=140, cwd=ROOT)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                return json.loads(p.stdout)['data']

            created = cli('session', 'create')
            sid = created['session_id']
            cli('request', sid, payload={'action':'goto','url':url})
            cli('request', sid, payload={'action':'fill','label':'姓名','text':'跨进程保留'})
            self.assertEqual(cli('request', sid, payload={'action':'inspect','css':'#name'})['value'], '跨进程保留')
            snap = cli('request', sid, payload={'action':'snapshot'})
            button = next(e for e in snap['elements'] if e.get('text') == '计数 0')
            cli('request', sid, payload={'action':'click','snapshot_id':snap['snapshot_id'],'ref':button['ref']})
            self.assertEqual(cli('request', sid, payload={'action':'text','css':'#count'})['text'], '计数 1')
            rejected = http('POST', f'/sessions/{sid}/actions', json.dumps(
                {'action':'click','css':'#count','name':'Cancel'}))
            self.assertEqual(rejected[1]['error']['code'], 'invalid_request')
            self.assertEqual(cli('request', sid, payload={'action':'text','css':'#count'})['text'], '计数 1')
            shot = cli('request', sid, payload={'action':'screenshot'})
            self.assertTrue(Path(shot['path']).exists())
            invalid = http('POST', f'/sessions/{sid}/actions', '{')
            self.assertEqual(invalid[1]['error']['code'], 'invalid_json')
            self.assertEqual(http('POST', '/sessions', '[]')[1]['error']['code'], 'invalid_request')
            self.assertEqual(http('POST', '/sessions', '{}', {'Origin':'https://evil.example'})[0], 403)
            self.assertEqual(http('GET', '/health', headers={'Host':'evil.example'})[0], 403)
            for _ in range(5):
                status, oversized = http('POST', '/sessions', 'x' * (1024*1024+1))
                self.assertEqual(status, 413)
                self.assertEqual(oversized['error']['code'], 'request_too_large')
            self.assertEqual(http('GET', '/missing')[1]['error']['code'], 'not_found')
            self.assertTrue(http('GET','/health')[1]['ok'])
            cli('request', sid, payload={'action':'evaluate','expression':
                "() => { localStorage.setItem('restart','长期身份'); document.cookie='restart=yes; Max-Age=86400; Path=/'; }"})
            cli('stop')
            self.assertEqual(proc.wait(timeout=20), 0)
            proc.stdout.close()
            proc = subprocess.Popen([sys.executable, '-u', str(ROOT / 'dybrowser.py'),
                'serve', '--port', '0', '--data-dir', temp.name],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8')
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
            port = json.loads(lines.get(timeout=25))['data']['port']
            records = cli('session', 'list')
            self.assertEqual(next(r for r in records if r['session_id'] == sid)['state'], 'dormant')
            cli('request', sid, payload={'action':'goto','url':url})
            state = cli('request', sid, payload={'action':'evaluate','expression':
                "() => ({value:localStorage.getItem('restart'), cookie:document.cookie})"})
            self.assertEqual(state['result']['value'], '长期身份')
            self.assertIn('restart=yes', state['result']['cookie'])
            cli('session', 'close', sid)
            self.assertEqual(cli('session', 'resume', sid)['session_id'], sid)
            cli('session', 'forget', sid)
            self.assertNotIn(sid, [r['session_id'] for r in cli('session', 'list')])
            cli('stop')
            self.assertEqual(proc.wait(timeout=20), 0)
        finally:
            if proc.poll() is None:
                if port is not None:
                    try:
                        http('POST', '/shutdown', '{}')
                        proc.wait(timeout=20)
                    except Exception:
                        proc.terminate()
                        proc.wait(timeout=10)
                else:
                    proc.terminate()
                    proc.wait(timeout=10)
            proc.stdout.close()
            log.close()
            fixture.shutdown()
            fixture.server_close()
            temp.cleanup()
