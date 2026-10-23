const { chromium } = require("../desktop/node_modules/playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
const PCMResampler = require("../server/core_v2/web/pcm.js");
for (const rate of [16000, 44100, 48000]) {
  const resampler = new PCMResampler(rate),
    result = [];
  for (let offset = 0; offset < rate; offset += 2048) {
    const chunk = Float32Array.from(
      { length: Math.min(2048, rate - offset) },
      (_, i) => Math.sin((2 * Math.PI * 1000 * (i + offset)) / rate) * 0.5,
    );
    result.push(...resampler.push(chunk));
  }
  assert(Math.abs(result.length - 16000) <= 1);
  for (let i = 0; i < result.length; i++)
    assert(
      Math.abs(
        result[i] / 32768 - Math.sin((2 * Math.PI * 1000 * i) / 16000) * 0.5,
      ) < 0.003,
    );
}
(async () => {
  const directory = fs.mkdtempSync(
    path.join(os.tmpdir(), "shengjian-core-ui-"),
  );
  const port = Number(process.env.SHENGJIAN_CORE_UI_PORT || 18779),
    origin = `http://127.0.0.1:${port}`;
  const python =
    process.env.SHENGJIAN_TEST_PYTHON || path.resolve(".venv/bin/python");
  const server = spawn(
    python,
    ["tests/fixtures/core_ui_server.py", directory, String(port)],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  let diagnostic = "";
  server.stderr.on("data", (d) => (diagnostic += d.toString().slice(0, 4000)));
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try {
        const r = await fetch(origin + "/shengjian/api/v2/health");
        if (r.ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!ready) throw new Error("Fixture did not start: " + diagnostic);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.SHENGJIAN_UI_BROWSER
        ? { executablePath: process.env.SHENGJIAN_UI_BROWSER }
        : {}),
    });
    const context = await browser.newContext({
        viewport: { width: 1100, height: 780 },
      }),
      page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(origin + "/shengjian/api/v2/console");
    await page.getByLabel("用户名", { exact: true }).fill("browser-test");
    await page.getByLabel("密码", { exact: true }).fill("browser-password-123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator("#workspace").waitFor({ state: "visible" });
    await page.locator("#speak").uncheck();
    await page.locator("#prompt").fill("测试对话");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("已收到你的消息。", { exact: true }).waitFor();
    await page.getByRole("button", { name: "设备", exact: true }).click();
    await page.getByText("登记电脑连接器", { exact: true }).click();
    await page.getByLabel("设备名称").fill("测试电脑");
    await page.getByRole("button", { name: "登记任务与状态能力" }).click();
    await page
      .getByRole("heading", { name: "测试电脑", exact: true })
      .waitFor();
    await page.getByLabel("执行任务", { exact: true }).check();
    await page.getByRole("button", { name: "对话", exact: true }).click();
    await page
      .locator("#destination")
      .selectOption({ label: "测试电脑 · 离线" });
    await page.locator("#prompt").fill("整理测试资料");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page
      .locator("#task-detail")
      .getByRole("heading", { name: "整理测试资料" })
      .waitFor();
    await page
      .locator("#task-detail")
      .getByRole("button", { name: "取消任务" })
      .click();
    await page
      .locator("#task-detail")
      .getByText("已取消", { exact: true })
      .waitFor();
    await page.getByRole("button", { name: "对话", exact: true }).click();
    const out = path.resolve("artifacts/core-ui");
    fs.mkdirSync(out, { recursive: true });
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      for (const viewport of [
        { width: 1100, height: 780 },
        { width: 390, height: 844 },
      ]) {
        await page.setViewportSize(viewport);
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          "horizontal overflow",
        );
        await page.screenshot({
          path: path.join(out, `${colorScheme}-${viewport.width}.png`),
          fullPage: true,
        });
      }
    }
    assert.deepEqual(errors, []);
    await page.getByRole("button", { name: "退出登录" }).click();
    await page.locator("#auth").waitFor({ state: "visible" });
    console.log(
      "Core UI: login, chat, enroll, grant, durable task, cancellation, light/dark, mobile passed",
    );
  } finally {
    if (browser) await browser.close();
    server.kill("SIGTERM");
    await new Promise((r) => {
      if (server.exitCode !== null) r();
      else server.once("exit", r);
    });
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
