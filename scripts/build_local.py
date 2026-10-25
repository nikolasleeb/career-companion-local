#!/usr/bin/env python3
"""Stamp a local source build; never installs, starts or restarts the app."""
import subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
try:
 revision=git('rev-parse','HEAD')
 if git('status','--porcelain','--untracked-files=normal'):revision+='-dirty'
except (OSError,subprocess.CalledProcessError):revision='unknown'
print('Building source revision '+revision,flush=True)
subprocess.run(['docker','compose','build','--build-arg','APP_REVISION='+revision,'--build-arg','APP_BUILT_AT='+datetime.now(timezone.utc).isoformat(),'--build-arg','APP_CHANNEL=source',*sys.argv[1:]],cwd=root,check=True)
