"""Small, separate portfolio evidence library. No writes to source databases."""
import hashlib, json, math, sqlite3, statistics
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, project TEXT NOT NULL, origin TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, captured_utc TEXT NOT NULL, evidence_kind TEXT NOT NULL, local_copy TEXT);
CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY, project TEXT NOT NULL, statement TEXT NOT NULL, status TEXT NOT NULL, source_id TEXT REFERENCES sources, limitation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capabilities(skill_id TEXT PRIMARY KEY, skill TEXT NOT NULL, status TEXT CHECK(status IN ('demonstrated','with_tools','needs_development','untested')), evidence TEXT NOT NULL, personal_contribution TEXT NOT NULL, assistance TEXT NOT NULL, next_step TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, state TEXT NOT NULL, result_json TEXT, provider TEXT, run_id TEXT, tool_calls INTEGER NOT NULL DEFAULT 0, artifact_sha256 TEXT, updated_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS validations(validation_id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs, verdict TEXT NOT NULL CHECK(verdict IN ('ACCEPT','REJECT','ERROR','NOT_RUN')), task_accepted INTEGER CHECK(task_accepted IN (0,1)), validator TEXT NOT NULL, evidence TEXT NOT NULL, CHECK((verdict='ACCEPT' AND task_accepted IS 1) OR (verdict='REJECT' AND task_accepted IS 0) OR (verdict IN ('ERROR','NOT_RUN') AND task_accepted IS NULL)));
CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs, kind TEXT NOT NULL, payload TEXT NOT NULL, utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metrics(metric_id TEXT PRIMARY KEY, project TEXT NOT NULL, build TEXT NOT NULL, capture_id TEXT NOT NULL, mode TEXT NOT NULL, name TEXT NOT NULL, value REAL, unit TEXT NOT NULL, missing_reason TEXT, source_id TEXT REFERENCES sources);
CREATE TABLE IF NOT EXISTS consents(consent_id TEXT PRIMARY KEY, source TEXT NOT NULL, scope TEXT NOT NULL, router_grant INTEGER NOT NULL CHECK(router_grant=0), recorded_utc TEXT NOT NULL);
'''
def connect(path):
    db=sqlite3.connect(path, timeout=5); db.execute('PRAGMA foreign_keys=ON'); db.executescript(SCHEMA)
    definition=db.execute("SELECT sql FROM sqlite_master WHERE name='validations'").fetchone()[0]
    if 'task_accepted IS 1' not in definition:
        db.close()
        raise ValueError('Incompatible demo schema; automatic migrations are not supported')
    return db
def verdict(accepted):
    if accepted is True: return 'ACCEPT',1
    if accepted is False: return 'REJECT',0
    return 'ERROR',None
def event(db, event_id, job_id, kind, payload):
    db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',(event_id,job_id,kind,json.dumps(payload,sort_keys=True),now()))
def export_events(db, path):
    rows=[dict(zip(('event_id','job_id','kind','payload','utc'),r)) for r in db.execute('SELECT * FROM events ORDER BY utc,event_id')]
    Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
def backup(src, destination):
    with closing(sqlite3.connect(Path(src).as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(destination)) as target: source.backup(target)
def frame_metrics(frame_times_ms):
    if not frame_times_ms or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in frame_times_ms): raise ValueError('Positive finite frame intervals required')
    slow=sorted(frame_times_ms,reverse=True)[:max(1,math.ceil(len(frame_times_ms)*0.01))]
    return {'fps':1000/statistics.mean(frame_times_ms),'one_percent_low_fps':1000/statistics.mean(slow),'frames':len(frame_times_ms),'method':'1000 / arithmetic mean interval; 1% low uses slowest ceil(N*.01) intervals'}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--graphics-capture',type=Path);args=parser.parse_args()
    if args.graphics_capture:
        data=json.loads(args.graphics_capture.read_text(encoding='utf-8'))
        result={'build':data['build'],'capture_id':data['capture_id'],'mode':data['mode'],'base':frame_metrics(data['base_intervals_ms']) if data.get('base_intervals_ms') else None,'displayed':frame_metrics(data['display_intervals_ms']) if data.get('display_intervals_ms') else None,'latency_ms':data.get('latency_ms'),'limits':'No base FPS inferred from FG multiplier. Missing latency stays null.'}
        print(json.dumps(result,indent=2))
