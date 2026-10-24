import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv('DATA_DIR', str(ROOT / 'local-data')))
DB_PATH = DATA_DIR / 'career.sqlite3'
CONTENT_DIR = Path(os.getenv('CONTENT_DIR', str(ROOT / 'data')))
if not CONTENT_DIR.exists():
    CONTENT_DIR = ROOT.parent / 'data'
STATIC_DIR = Path(os.getenv('STATIC_DIR', str(ROOT.parent / 'frontend' / 'dist')))
MAX_UPLOAD = 10 * 1024 * 1024
MAX_TEXT = 100_000
MODEL = os.getenv('OPENAI_MODEL', 'gpt-5.6-terra')
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
ONET_KEY = os.getenv('ONET_API_KEY', '')
ADZUNA_ID = os.getenv('ADZUNA_APP_ID', '')
ADZUNA_KEY = os.getenv('ADZUNA_APP_KEY', '')
ENABLE_JOBSPY = os.getenv('ENABLE_JOBSPY', 'false').lower() == 'true'
ENABLE_WEB_SEARCH = os.getenv('ENABLE_WEB_SEARCH', 'true').lower() == 'true'
COOKIE_SECURE = False

def capabilities():
    return {'deployment': 'local','openai': bool(OPENAI_KEY), 'onet': bool(ONET_KEY),
            'adzuna': bool(ADZUNA_ID and ADZUNA_KEY), 'jobspy': ENABLE_JOBSPY,
            'web_search': bool(OPENAI_KEY and ENABLE_WEB_SEARCH), 'model': MODEL}

# This edition supports local browser access only. These hosts are not configurable.
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
ALLOW_SERVER_AI_KEY = False
VAULT_KEY_FILE = Path(os.getenv('VAULT_KEY_FILE', str(ROOT / 'local-secrets' / 'vault.key')))
GLOBAL_TASK_LIMIT = int(os.getenv('GLOBAL_TASK_LIMIT', '4'))
if os.getenv('CAREER_ENV', 'local') != 'local':
    raise RuntimeError('This edition supports localhost only.')
