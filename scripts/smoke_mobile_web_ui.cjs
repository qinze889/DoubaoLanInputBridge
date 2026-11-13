// Browser-level regression for the real Python-generated phone page.
// No user data, no live networking and no production credentials.
const { spawnSync } = require('node:child_process')
const { createRequire } = require('node:module')
const fs = require('node:fs/promises')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const assert = require('node:assert/strict')

const root = path.resolve(__dirname, '..')
const requireDesktop = createRequire(path.join(root, 'desktop/package.json'))
const { chromium } = requireDesktop('playwright')
const out = path.join(root, 'build', 'mobile-ui-check')

async function main() {
  await fs.mkdir(out, { recursive: true })
  const htmlPath = path.join(out, 'phone.html')
  const script = [
    'import pathlib, sys',
    'sys.path.insert(0, str(pathlib.Path("src").resolve()))',
    'import gui_app',
    'pathlib.Path(sys.argv[1]).write_text(gui_app.html_page("ui-fixture-not-a-real-key", "http://127.0.0.1:8765/?key=ui-fixture-not-a-real-key"), encoding="utf-8")',
  ].join('; ')
  const generated = spawnSync('python', ['-c', script, htmlPath], {
    cwd: root, encoding: 'utf8',
    env: { ...process.env, PYTHONUTF8: '1', DOUBAO_BRIDGE_DATA_DIR: path.join(out, 'empty-data') },
  })
  assert.equal(generated.status, 0, 'Python mobile fixture generation failed: ' + generated.stderr)

  const browser = await chromium.launch({ headless: true })
  try {
    const viewportCases = [
      { width: 320, height: 568 },
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
    ]
    const page = await browser.newPage({ viewport: viewportCases[0], deviceScaleFactor: 1 })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(pathToFileURL(htmlPath).href)
    await page.locator('#text').waitFor()
    await page.locator('.mobile-brand').waitFor()
    for (const viewport of viewportCases) {
      await page.setViewportSize(viewport)
      const sizing = await page.evaluate(() => {
        const documentWidth = document.documentElement.scrollWidth
        const actualViewport = window.innerWidth
        const critical = ['.app-shell', '.mobile-brand', '.tool-card',
          '.mobile-tool-switches', '.send-panel', '#text', '#send']
        const clipped = critical.flatMap(selector => [...document.querySelectorAll(selector)]
          .filter(element => {
            const rect = element.getBoundingClientRect()
            return rect.left < -2 || rect.right > actualViewport + 2
          }).map(element => ({ selector, left: element.getBoundingClientRect().left,
            right: element.getBoundingClientRect().right })))
        return { documentWidth, actualViewport, clipped }
      })
      assert(sizing.documentWidth <= viewport.width + 2, 'Page overflows ' + viewport.width + 'px viewport: ' + JSON.stringify(sizing))
      assert.deepEqual(sizing.clipped, [], 'Controls are clipped at ' + viewport.width + 'px')
      await page.screenshot({ path: path.join(out, 'phone-' + viewport.width + '.png'), fullPage: true })
    }
    assert.deepEqual(errors, [], 'Mobile page has browser errors')
    console.log(JSON.stringify({ passed: true, widths: viewportCases.map(v => v.width), errors }))
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
