import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from demo import resume, self_test, start
from evidence import connect, now

class DemoTests(unittest.TestCase):
    def test_crash_and_two_resumes(self):
        result = self_test()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['tool_calls'], 1)

    def test_existing_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            sentinel = Path(d) / 'original.txt'
            sentinel.write_text('keep', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                start(d)
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_missing_job_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                resume(d)
            self.assertFalse((Path(d) / 'demo.sqlite3').exists())

    def test_uncertain_state_stops(self):
        with tempfile.TemporaryDirectory() as d:
            db = connect(Path(d) / 'demo.sqlite3')
            with db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                           ('demo', 'INFLIGHT', None, None, None, 0, None, now()))
            db.close()
            with self.assertRaisesRegex(ValueError, 'NEEDS_RECONCILIATION'):
                resume(d)
            self.assertFalse((Path(d) / 'result.json').exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
