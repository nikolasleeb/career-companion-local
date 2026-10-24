"""Bundled, attributed writing principles; never applicant evidence or live research."""
import copy
import hashlib
import json
from . import config

def catalog():
    rows=json.loads((config.CONTENT_DIR/'guidance.json').read_text())
    version='writing-guide-'+hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()[:12]
    return {'version':version,'items':rows}

def selected(topic):
    value=catalog()
    value['items']=[r for r in value['items'] if r.get('topic') in (topic,'formatting') or r['id']=='guide_evidence']
    return copy.deepcopy(value)
