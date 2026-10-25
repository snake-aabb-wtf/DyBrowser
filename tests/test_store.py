import tempfile
import unittest
from pathlib import Path
from helpers import ROOT

try:
    from dybrowser.store import SessionStore
except ImportError:
    SessionStore = None


class StoreTests(unittest.TestCase):
    def test_records_survive_reopen_and_profile_is_unique(self):
        self.assertIsNotNone(SessionStore, 'Persistent registry is not implemented')
        from dybrowser.protocol import ToolError
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder:
            store = SessionStore(Path(folder))
            record = store.create('a'*32, 'profile', True)
            again = SessionStore(Path(folder))
            self.assertEqual(again.get('a'*32), record)
            self.assertTrue(again.get('a'*32)['headless'])
            with self.assertRaises(ToolError):
                again.create('b'*32, 'profile', False)
            again.delete('a'*32)
            self.assertIsNone(store.get('a'*32))

    def test_corrupt_registry_is_reported_without_overwriting(self):
        self.assertIsNotNone(SessionStore, 'Persistent registry is not implemented')
        from dybrowser.protocol import ToolError
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder:
            path = Path(folder) / 'state' / 'sessions.sqlite3'
            path.parent.mkdir()
            path.write_bytes(b'broken registry')
            with self.assertRaises(ToolError) as error:
                SessionStore(Path(folder))
            self.assertEqual(error.exception.code, 'session_store_error')
            self.assertEqual(path.read_bytes(), b'broken registry')
