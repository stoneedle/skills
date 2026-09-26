"""Change just the known local route, preserving all other TOML entries."""
import datetime
import hashlib
import json
import sys
from pathlib import Path
import tomllib
import re

root = Path(__file__).resolve().parent
config = Path.home()/'.codex/config.toml'
old = config.read_bytes()
text = old.decode('utf-8')
doc = tomllib.loads(text)
direct = 'http://127.0.0.1:17841/v1'
bridge = 'http://127.0.0.1:17842/v1'
action = sys.argv[1]
assert action in ('connect', 'direct')
expected, desired = (direct, bridge) if action == 'connect' else (bridge, direct)
if doc.get('openai_base_url') == desired:
    print('Already configured:', desired)
    sys.exit(0)
assert doc.get('openai_base_url') == expected, 'Unexpected existing route; refusing overwrite'
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
backup = Path.home()/'.codex/repair-backups'/('tap-bridge-'+stamp)
backup.mkdir(parents=True)
(backup/'config.toml').write_bytes(old)
text, count = re.subn(r'(?m)^openai_base_url\s*=\s*[^\r\n]+',
    'openai_base_url = ' + json.dumps(desired), text)
assert count == 1
new = text.encode('utf-8')
updated = tomllib.loads(text)
updated['openai_base_url'] = doc['openai_base_url']
assert updated == doc, 'Unrelated settings changed'
assert config.read_bytes() == old, 'Concurrent config change detected'
temporary = config.with_name('config.toml.tap-bridge.tmp')
temporary.write_bytes(new)
temporary.replace(config)
with (root/'operations.jsonl').open('a',encoding='utf-8') as f:
    f.write(json.dumps({'time':stamp,'action':action,'file':str(config),'backup':str(backup),
        'before_sha256':hashlib.sha256(old).hexdigest(),'after_sha256':hashlib.sha256(new).hexdigest(),
        'old_url':expected,'new_url':desired})+'\n')
print('Route updated:',desired,'Backup:',backup)
