"""Read the non-personal build identity bundled with the client and server."""
import json
import re
from . import config

def current():
    try:
        value=json.loads((config.STATIC_DIR/'build-info.json').read_text()).get('build_id')
        if isinstance(value,str) and re.fullmatch(r'[a-f0-9]{32}',value):return value
    except (OSError,ValueError,AttributeError):
        pass
    return None
