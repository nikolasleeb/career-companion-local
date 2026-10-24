"""Fail before publishing personal machine paths, credentials, or runtime data."""
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(p, re.I) for p in (
    r'/Users/[A-Za-z0-9_.-]+/', r'/home/[A-Za-z0-9_.-]+/',
    r'[A-Z]:\\Users\\[^\\]+\\', r'gh[pousr]_[A-Za-z0-9]{30,}',
    r'github_pat_[A-Za-z0-9_]{30,}', r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
)]


def audit():
    try:
        names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    except subprocess.CalledProcessError:
        raise SystemExit('Initialize the clean source repository before auditing.')
    problems = []
    for name in set(names):
        if not name or name == 'scripts/audit_public.py':
            continue
        path = ROOT/name
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if any(part in ('local-data','local-secrets','.private-credentials','.private-backups') for part in parts) or path.suffix in ('.key','.pem','.sqlite3','.db') or path.name == '.env':
            problems.append(name+': runtime/credential file')
        blobs = [(name,path.read_bytes())]
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                blobs = [(name+'!'+entry,archive.read(entry)) for entry in archive.namelist() if not entry.endswith('/')]
        for label, raw in blobs:
            text = raw.decode('utf-8',errors='ignore')
            if any(pattern.search(text) for pattern in PATTERNS):
                problems.append(label+': machine path or credential signature')
    if problems:
        raise SystemExit('\n'.join(sorted(set(problems))))
    print('Public source audit passed: no credential signatures, personal home paths, or runtime data.')


if __name__ == '__main__':
    audit()
