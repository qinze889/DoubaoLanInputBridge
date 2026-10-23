"""Local-only administrative client. Never place admin tokens in shell arguments."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import urllib.request


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/var/lib/shengjian-core'))
    commands = parser.add_subparsers(dest='command', required=True)
    invite = commands.add_parser('invite')
    invite.add_argument('--credits', type=int, default=1000)
    invite.add_argument('--lifetime', type=int, default=86400)
    invite.add_argument('--output', type=Path, required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; refusing to replace it')
    if args.command == 'backup':
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect('file:'+str(args.data/'core.sqlite3')+'?mode=ro',uri=True) as source, sqlite3.connect(args.output) as target:
            source.backup(target)
        print('Consistent SQLite snapshot saved')
        return
    token = (args.data/'admin.token').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:18767/shengjian/api/v2/admin/invites',
        data=json.dumps({'credits':args.credits,'uses':1,'lifetime':args.lifetime}).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response:
        code = json.load(response)['invite']
    private_write(args.output, '入口：https://test.xjiaoai.com/shengjian/api/v2/console\n一次性邀请码：'+code+'\n请自行设置用户名和密码。邀请码只使用一次；请勿转发此文件。\n')
    print('One-use invitation saved privately')


if __name__ == '__main__':
    main()
