"""Build-time pinned engine cache; the shipped App never needs npm on first use."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
target = root/'tools/dsh'
package = target/'node_modules/@deepseek-ai/dsh/package.json'
version = '0.2.1-rc.2'
lock = root/'packaging/harness/package-lock.json'
installed_lock = target/'package-lock.json'
if not package.exists() or json.loads(package.read_text())['version'] != version or not installed_lock.exists() or hashlib.sha256(installed_lock.read_bytes()).digest() != hashlib.sha256(lock.read_bytes()).digest():
    node, npm = shutil.which('node'), shutil.which('npm')
    if not node or not npm:
        raise SystemExit('Build needs Node.js and npm to prepare the bundled Harness')
    cli = Path(node).parent/'node_modules/npm/bin/npm-cli.js'
    if not cli.exists(): cli = Path(npm).resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name in ['package.json', 'package-lock.json']:
        shutil.copyfile(root/'packaging/harness'/name, target/name)
    subprocess.run([node, str(cli), 'ci', '--prefix', str(target), '--ignore-scripts', '--no-audit', '--no-fund'], check=True)
assert json.loads(package.read_text())['version'] == version
print('Pinned Harness is ready for packaging:', version)
