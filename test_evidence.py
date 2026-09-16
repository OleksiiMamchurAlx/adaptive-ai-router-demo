import json,math,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from evidence import connect,event,export_events,frame_metrics,backup,verdict,now

class EvidenceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'test.sqlite3';self.db=connect(self.path)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def test_duplicate_event(self):
        event(self.db,'a',None,'test',{});event(self.db,'a',None,'test',{});self.assertEqual(self.db.execute('select count(*) from events').fetchone()[0],1)
    def test_error_is_unknown(self):self.assertEqual(verdict(None),('ERROR',None))
    def test_rejection_is_false(self):self.assertEqual(verdict(False),('REJECT',0))
    def test_false_accept_blocked(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',('a',None,'ACCEPT',0,'v','e'))
    def test_null_accept_blocked(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',('a',None,'ACCEPT',None,'v','e'))
    def test_null_reject_blocked(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',('a',None,'REJECT',None,'v','e'))
    def test_error_cannot_be_false_feedback(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',('a',None,'ERROR',0,'v','e'))
    def test_transaction_rollback(self):
        try:
            with self.db:event(self.db,'a',None,'test',{});raise RuntimeError()
        except RuntimeError:pass
        self.assertEqual(self.db.execute('select count(*) from events').fetchone()[0],0)
    def test_backup_restore(self):
        event(self.db,'a',None,'test',{});self.db.commit();backup(self.path,self.root/'restore.db')
        with closing(sqlite3.connect(self.root/'restore.db')) as restored:self.assertEqual(restored.execute('pragma integrity_check').fetchone()[0],'ok');self.assertEqual(restored.execute('select count(*) from events').fetchone()[0],1)
    def test_repeatable_export(self):
        event(self.db,'a',None,'test',{});p=self.root/'out.jsonl';export_events(self.db,p);a=p.read_bytes();export_events(self.db,p);self.assertEqual(a,p.read_bytes())
    def test_missing_metric_null(self):
        self.db.execute('insert into metrics values (?,?,?,?,?,?,?,?,?,?)',('a','graphics','test','test','NOT_RUN','latency',None,'ms','no capture',None));self.assertIsNone(self.db.execute('select value from metrics').fetchone()[0])
    def test_frame_math(self):self.assertEqual(frame_metrics([10]*100)['fps'],100)
    def test_one_percent_low(self):self.assertEqual(frame_metrics([10]*99+[20])['one_percent_low_fps'],50)
    def test_bad_frame_data(self):
        for values in ([],[True],[0],[-1],[math.nan],[math.inf]):
            with self.assertRaises(ValueError):frame_metrics(values)
    def test_orphan_validation(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?)',('a','unknown','ACCEPT',1,'v','e'))
    def test_consent_is_not_router_grant(self):
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('insert into consents values (?,?,?,?,?)',('a','owner','current plan',1,now()))
if __name__=='__main__':unittest.main(verbosity=2)
