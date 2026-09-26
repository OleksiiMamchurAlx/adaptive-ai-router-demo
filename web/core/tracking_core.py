"""Browser storage adapter for the pinned native workflow.

The page serializes all access with Web Locks. This module only supplies the
SQLite connection interface; routing, transitions and validation remain in the
unmodified native modules.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class RoutingTracker:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.parent != Path('/data') or self.path.suffix != '.sqlite3':
            raise ValueError('browser database must be inside /data')

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=1000')
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _write_connection(self):
        with self._connection() as db:
            yield db
