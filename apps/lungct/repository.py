"""One local SQLite transaction serializes single-operator research writes."""
from contextlib import contextmanager, closing
import json
from pathlib import Path
import sqlite3
from .core import encoded

TABLES = ('projects', 'studies', 'series', 'drafts', 'findings', 'revisions', 'runs', 'snapshots', 'exports', 'sources')


class Repository:
    def __init__(self, root):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'research.sqlite3'
        with closing(self.connect()) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
            conn.execute('INSERT OR IGNORE INTO state VALUES(1, ?)', (encoded({k:{} for k in TABLES}),))
            conn.commit()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            state = json.loads(conn.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            yield state
            conn.execute('UPDATE state SET body=? WHERE id=1', (encoded(state),))
            conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally:
            conn.close()

    def read(self):
        conn = self.connect()
        try:
            return json.loads(conn.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        finally:
            conn.close()
