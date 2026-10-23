const { spawn } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const url = 'http://127.0.0.1:1421';
const server = spawn(process.execPath, [path.join(root, 'desktop/node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', '1421', '--strictPort'], {cwd:path.join(root, 'desktop'), stdio:'inherit'});
let exited = false;
server.on('exit', () => { exited = true; });
(async () => {
  try {
    let ready = false;
    for (let i = 0; i < 100 && !exited; i++) {
      try { ready = (await fetch(url)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!ready || exited) throw Error('UI preview server did not start');
    const result = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [path.join(__dirname, 'smoke_desktop_ui.cjs')], {cwd:root, env:{...process.env, SHENGJIAN_UI_URL:url}, stdio:'inherit'});
      child.on('error', reject);
      child.on('exit', code => resolve(code ?? 1));
    });
    process.exitCode = result;
  } finally { server.kill(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
