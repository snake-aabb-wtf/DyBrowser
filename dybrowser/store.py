"""Durable identity registry; Chrome continues to own cookies/site storage."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

from .protocol import ToolError


class DataDirectoryLease:
    """OS lock released automatically if the service process terminates."""
    def __init__(self, root):
        self.path = Path(root) / 'state' / 'service.lock'
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open('a+b')
        try:
            if file.seek(0, 2) == 0:
                file.write(b'\0')
                file.flush()
            file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            file.close()
            raise ToolError('data_dir_in_use', 'Another service is using this data directory') from exc
        self.file = file

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


class SessionStore:
    def __init__(self, root):
        self.path = Path(root) / 'state' / 'sessions.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL UNIQUE,
                headless INTEGER NOT NULL,
                created_at TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            with db:
                yield db
        except sqlite3.IntegrityError as exc:
            raise ToolError('profile_in_use', 'Profile already has a persistent Session') from exc
        except sqlite3.Error as exc:
            raise ToolError('session_store_error', f'Cannot read/write Session registry: {exc}') from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def record(row):
        if row is None:
            return None
        value = dict(row)
        value['headless'] = bool(value['headless'])
        return value

    def get(self, sid):
        with self.connection() as db:
            return self.record(db.execute('SELECT * FROM sessions WHERE session_id=?', (sid,)).fetchone())

    def find_profile(self, profile):
        with self.connection() as db:
            return self.record(db.execute('SELECT * FROM sessions WHERE profile_id=?', (profile,)).fetchone())

    def list(self):
        with self.connection() as db:
            return [self.record(row) for row in db.execute('SELECT * FROM sessions ORDER BY created_at, session_id')]

    def create(self, sid, profile, headless):
        created = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (sid, profile, int(headless), created))
        return self.get(sid)

    def set_headless(self, sid, headless):
        with self.connection() as db:
            db.execute('UPDATE sessions SET headless=? WHERE session_id=?', (int(headless), sid))

    def delete(self, sid):
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE session_id=?', (sid,))
