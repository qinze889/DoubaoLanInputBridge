"""Install app-owned media tools in the existing Harness home, outside app signing."""
import json
import os
from pathlib import Path
import tempfile


def atomic(path, content):
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(content)
        os.chmod(name,0o600);Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def install_media_plugin(directory):
    home=Path(directory)/'home';home.mkdir(mode=0o700,parents=True,exist_ok=True)
    patch=home/'cordis.patch.yml'
    try:rows=json.loads(patch.read_text()) if patch.exists() else []
    except (ValueError,OSError):return False
    if not isinstance(rows,list):return False
    target=home/'shengjian-media.mjs';source=Path(__file__).with_name('dsh_media.mjs').read_bytes()
    if not target.exists() or target.read_bytes()!=source:atomic(target,source)
    entry={'id':'shengjian-conversation-media','name':str(target)}
    for row in rows:
        if isinstance(row,dict) and isinstance(row.get('insert'),list):
            for old in row['insert']:
                if isinstance(old,dict) and old.get('id')==entry['id']:
                    if old.get('name')!=str(target):old['name']=str(target);atomic(patch,(json.dumps(rows,ensure_ascii=False)+'\n').encode())
                    return True
    rows.append({'insert':[entry]})
    atomic(patch,(json.dumps(rows,ensure_ascii=False)+'\n').encode())
    return True
