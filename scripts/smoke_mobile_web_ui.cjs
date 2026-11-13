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
  const script = [
    'import pathlib, sys',
    'sys.path.insert(0, str(pathlib.Path("src").resolve()))',
    'import gui_app',
    'gui_app.IS_MACOS = sys.argv[2] == "mac"',
    'pathlib.Path(sys.argv[1]).write_text(gui_app.html_page("ui-fixture-not-a-real-key", "http://127.0.0.1:8765/?key=ui-fixture-not-a-real-key"), encoding="utf-8")',
  ].join('; ')
  for (const platform of ['windows', 'mac']) {
    const htmlPath = path.join(out, 'phone-' + platform + '.html')
    const generated = spawnSync('python', ['-c', script, htmlPath, platform], {
      cwd: root, encoding: 'utf8',
      env: { ...process.env, PYTHONUTF8: '1', DOUBAO_BRIDGE_DATA_DIR: path.join(out, 'empty-data-' + platform) },
    })
    assert.equal(generated.status, 0, 'Mobile ' + platform + ' HTML generation failed: ' + generated.stderr)
  }

  const browser = await chromium.launch({ headless: true })
  try {
    const viewportCases = [
      { width: 320, height: 568 },
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
    ]
    for (const platform of ['windows', 'mac']) {
      const htmlPath = path.join(out, 'phone-' + platform + '.html')
      const page = await browser.newPage({ viewport: viewportCases[0], deviceScaleFactor: 1 })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto(pathToFileURL(htmlPath).href)
      await page.locator('#text').waitFor()
      await page.locator('.mobile-brand').waitFor()
      async function assertNoOverflow(viewport) {
        const sizing = await page.evaluate(() => {
          const actualViewport = window.innerWidth
          const documentWidth = document.documentElement.scrollWidth
          // Check all rendered elements, not only the initial top-level cards.
          // overflow-x: clip can hide a layout bug, but bounding boxes still expose it.
          const clipped = [...document.querySelectorAll('body *')]
            .filter(el => {
              if (el.classList.contains('file-input-native') || el.closest('[hidden]')) return false
              const style = getComputedStyle(el)
              if (style.display === 'none' || style.visibility === 'hidden' || style.position === 'fixed') return false
              const rect = el.getBoundingClientRect()
              return rect.width > 4 && (rect.left < -2 || rect.right > actualViewport + 2)
            })
            .slice(0, 12)
            .map(el => {
              const rect = el.getBoundingClientRect()
              return { tag: el.tagName, id: el.id, cls: String(el.className).slice(0, 50),
                left: Math.round(rect.left), right: Math.round(rect.right) }
            })
          return { documentWidth, actualViewport, clipped }
        })
        assert(sizing.documentWidth <= viewport.width + 2,
          platform + ' page overflows ' + viewport.width + 'px viewport: ' + JSON.stringify(sizing))
        assert.deepEqual(sizing.clipped, [],
          platform + ' visible controls are clipped at ' + viewport.width + 'px')
      }
      for (const viewport of viewportCases) {
        await page.setViewportSize(viewport)
        await assertNoOverflow(viewport)
        await page.screenshot({
          path: path.join(out, 'phone-' + platform + '-' + viewport.width + '.png'),
          fullPage: true
        })
      }
      // Opening tools and adding long text must not break the narrow screen.
      await page.setViewportSize(viewportCases[0])
      await page.locator('#toggleAssistTools').click()
      await page.locator('#toggleFileTools').click()
      await page.locator('#toggleInputSize').click()
      await page.locator('#text').fill('超长内容验证：' + '语音输入文字'.repeat(80) + 'x'.repeat(120))
      await assertNoOverflow(viewportCases[0])
      await page.screenshot({ path: path.join(out, 'phone-' + platform + '-expanded-320.png'), fullPage: true })
      assert.deepEqual(errors, [], platform + ' mobile page has browser errors')
      await page.close()
    }
    console.log(JSON.stringify({ passed: true, platforms: ['windows', 'mac'],
      widths: viewportCases.map(v => v.width), extendedTools: true }))
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
