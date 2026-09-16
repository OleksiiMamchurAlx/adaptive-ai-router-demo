"""Portable deterministic gates. Pattern checks are not a universal DLP system."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from datetime import datetime, timezone


class Blocked(ValueError):
    """A bounded reason code, never raw input or a private path."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def path_ok(name):
    p = PurePosixPath(name)
    return (bool(name) and not p.is_absolute() and '\\' not in name
            and not any(x in ('..', '.', '') for x in name.split('/'))
            and ':' not in name and name == p.as_posix())


def scan(name, data):
    if not path_ok(name):
        raise Blocked('UNSAFE_RELATIVE_PATH')
    if Path(name).suffix.lower() in {'.db','.sqlite','.sqlite3','.dll','.exe','.pdb','.zip','.png','.jpg'}:
        raise Blocked('PRIVATE_OR_BINARY_FILE')
    if name.lower().endswith(('-wal','-shm')) or Path(name).name.lower() in {'auth.json','.env'}:
        raise Blocked('PRIVATE_STATE_FILE')
    if len(data) > 1_000_000 or b'\x00' in data:
        raise Blocked('BINARY_OR_SIZE_LIMIT')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise Blocked('NOT_UTF8') from None
    patterns = {
        'CREDENTIAL': r'(?i)\b(?:gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|sk-[a-z0-9_-]{20,}|csk-[a-z0-9]{20,}|tvly-[a-z0-9_-]{15,}|bearer\s+[a-z0-9._-]{12,})',
        'SECRET_ASSIGNMENT': r'(?i)(?:password|api[_-]?key|access[_-]?token)\s*["\x27]?\s*[:=]\s*["\x27][a-z0-9+/=_-]{12,}["\x27]',
        'PRIVATE_KEY': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'LOCAL_PATH': r'(?i)\b[a-z]:[\\/]|/(?:Users|home|mnt)/|\\\\[a-z0-9]+[\\/]',
        'PRIVATE_ENV': r'(?i)\bAlexK\b|AppData[\\/]|\.codex[\\/]|SteamLibrary[\\/]',
        'EMAIL': r'(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b',
        'SENSITIVE_SUBJECT': r'(?i)\b(?:' + 'W'+'SIB' + r'|pa' + r'tient|pass' + r'port|social insur' + r'ance|medical rec' + r'ord|legal ca' + r'se)\b',
    }
    for code, pattern in patterns.items():
        if re.search(pattern, text):
            raise Blocked(code)


def inventory(root):
    root = Path(root)
    found = {}
    for p in root.rglob('*'):
        rel = p.relative_to(root)
        if any(x in {'.git','__pycache__'} for x in rel.parts):
            continue
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            raise Blocked('LINK_NOT_ALLOWED')
        if p.is_file():
            data = p.read_bytes()
            scan(rel.as_posix(), data)
            found[rel.as_posix()] = data
    return found


def validate_project(value, approved):
    if set(value) != set(approved) | {'verification'}:
        raise Blocked('PROJECT_SCHEMA_KEYS')
    if any(value[k] != v for k,v in approved.items()):
        raise Blocked('UNREVIEWED_CLAIM')
    v = value['verification']
    keys = {'tests_passed','tests_failed','tests_skipped','scope','source_commit','verified_at','source_tree_sha256'}
    if not isinstance(v, dict) or set(v) != keys:
        raise Blocked('VERIFICATION_SCHEMA')
    if any(type(v[k]) is not int or v[k] < 0 for k in ('tests_passed','tests_failed','tests_skipped')):
        raise Blocked('INVALID_TEST_COUNT')
    if v['tests_passed'] < 1 or v['tests_failed'] or v['tests_skipped']:
        raise Blocked('TESTS_NOT_FULL_PASS')
    if v['scope'] != 'isolated-public-code-tests':
        raise Blocked('UNREVIEWED_SCOPE')
    if not re.fullmatch('[0-9a-f]{40}', v['source_commit']):
        raise Blocked('INVALID_SOURCE_COMMIT')
    if not re.fullmatch('[0-9a-f]{64}', v['source_tree_sha256']):
        raise Blocked('INVALID_SOURCE_TREE')
    try:
        at = datetime.fromisoformat(v['verified_at'])
        if at.tzinfo is None or at.utcoffset().total_seconds() != 0 or at > datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise Blocked('INVALID_VERIFIED_TIME') from None


def input_tree(files):
    return digest(canonical({n:digest(b) for n,b in sorted(files.items())
                            if n not in {'project.json','PUBLICATION_MANIFEST.json'}}))


def validate(root, trusted_policy=None):
    files = inventory(root)
    policy = trusted_policy or json.loads(files['publication-policy.json'])
    if set(files) != set(policy['allowed_files']):
        raise Blocked('ALLOWLIST_MISMATCH')
    for name, expected in policy['reviewed_hashes'].items():
        if digest(files[name]) != expected:
            raise Blocked('CONTENT_REVIEW_REQUIRED')
    expected_reviewed = set(files)-{'project.json','PUBLICATION_MANIFEST.json','publication-policy.json'}
    if set(policy['reviewed_hashes']) != expected_reviewed:
        raise Blocked('REVIEW_COVERAGE')
    project = json.loads(files['project.json'])
    validate_project(project, policy['approved_project'])
    if project['verification']['source_tree_sha256'] != input_tree(files):
        raise Blocked('TESTED_SOURCE_MISMATCH')
    manifest = json.loads(files['PUBLICATION_MANIFEST.json'])
    entries = manifest['files']
    expected = set(files)-{'PUBLICATION_MANIFEST.json'}
    if (len(entries) != len(expected) or {x['path'] for x in entries} != expected
            or manifest.get('excludes_self') is not True):
        raise Blocked('MANIFEST_MEMBERSHIP')
    for row in entries:
        if row['sha256'] != digest(files[row['path']]) or row['size_bytes'] != len(files[row['path']]):
            raise Blocked('MANIFEST_HASH')
    for name, data in files.items():
        if name.endswith('.md'):
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', data.decode()):
                if target.startswith(('https://','#')):
                    continue
                target = str(PurePosixPath(name).parent / target.split('#')[0])
                if not path_ok(target) or target not in files:
                    raise Blocked('BROKEN_OR_UNSAFE_LINK')
    return {'status':'PASS','files':len(files),'source_tree_sha256':input_tree(files)}


if __name__ == '__main__':
    import sys
    try:
        print(json.dumps(validate(Path(sys.argv[1] if len(sys.argv)>1 else '.')), sort_keys=True))
    except (Blocked, KeyError, ValueError):
        print('{"status":"BLOCKED","reason":"PUBLICATION_GATE"}')
        raise SystemExit(1)
