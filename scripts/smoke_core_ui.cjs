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
// Endpointing is bounded and does not open a paid ASR request for silence/clicks.
const VoiceEndpoint = require("../server/core_v2/web/vad.js");
{
  let starts = 0,
    ends = 0,
    samples = 0;
  const detector = new VoiceEndpoint({
    start: (chunks) => {
      starts++;
      samples += chunks.reduce((n, c) => n + c.length, 0);
    },
    data: (pcm) => (samples += pcm.length),
    end: () => ends++,
  });
  const silence = new Int16Array(320);
  const voice = new Int16Array(320).fill(3000);
  for (let i = 0; i < 100; i++) detector.push(silence);
  detector.push(voice); // One click, then silence.
  for (let i = 0; i < 100; i++) detector.push(silence);
  assert.equal(starts, 0);
  for (let i = 0; i < 30; i++) detector.push(voice);
  for (let i = 0; i < 46; i++) detector.push(silence);
  assert.equal(starts, 1);
  assert.equal(ends, 1);
  assert(samples < 32000);
  for (let i = 0; i < 1300; i++) detector.push(voice);
  assert(
    ends >= 2,
    "continuous speech is split before the 30 second ASR limit",
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
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let voiceText = null;
    let asrConnections = 0,
      finishes = 0,
      audioBytes = 0;
    await page.routeWebSocket(/\/voice\/asr$/, (socket) => {
      asrConnections++;
      socket.onMessage((data) => {
        if (typeof data !== "string") {
          audioBytes += data.length;
          return;
        }
        const control = JSON.parse(data);
        if (control.token) socket.send(JSON.stringify({ type: "asr.ready" }));
        if (control.type === "finish") {
          finishes++;
          socket.send(
            JSON.stringify({
              type: "asr.final",
              text: voiceText || "连续对话第" + finishes + "句",
            }),
          );
          socket.send(JSON.stringify({ type: "asr.finished" }));
        }
      });
    });
    // UI-only plain response stub; real unified task/session protocol is covered by smoke_harness_chat.
    await page.route('**/shengjian/api/v2/assistant/chat', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,action:'status',reply:'已收到你的消息。'})}));
    await page.goto(origin + "/shengjian/api/v2/console");
    await page.getByLabel("用户名", { exact: true }).fill("browser-test");
    await page.getByLabel("密码", { exact: true }).fill("browser-password-123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator("#workspace").waitFor({ state: "visible" });
    await page.locator("#speak").uncheck();
    await page.locator("#prompt").fill("测试对话");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("已收到你的消息。", { exact: true }).waitFor();
    const speechBodies = [];
    let speechDelay = 0;
    await page.route("**/shengjian/api/v2/voice/speech", async (route) => {
      speechBodies.push(route.request().postDataJSON());
      if (speechDelay)
        await new Promise((resolve) => setTimeout(resolve, speechDelay));
      await route.fulfill({
        status: 200,
        contentType: "audio/mpeg",
        body: "fixture-audio",
      });
    });
    await page.evaluate(() => {
      window.originalAudio = window.Audio;
      window.Audio = class {
        constructor(src) {
          this.src = src;
          this.ended = false;
        }
        play() {
          setTimeout(() => {
            this.ended = true;
            this.onended?.();
          }, 3);
          return Promise.resolve();
        }
        pause() {
          this.onpause?.();
        }
      };
    });
    await page.evaluate(() => speak("a".repeat(2501)));
    assert.deepEqual(
      speechBodies.map((body) => body.input.length),
      [1000, 1000, 501],
    );
    assert.equal(new Set(speechBodies.map((body) => body.request_id)).size, 3);
    speechBodies.length = 0;
    speechDelay = 100;
    await page.evaluate(async () => {
      const speaking = speak("a".repeat(1501));
      setTimeout(stopSpeech, 0);
      await speaking;
    });
    assert.equal(
      speechBodies.length,
      1,
      "stopping speech prevents the next synthesis request",
    );
    speechDelay = 0;
    speechBodies.length = 0;
    // Real-time conversation: one microphone grant, automatic send, a second turn,
    // interruption during playback, then background shutdown with no retry.
    await page.locator("#destination").selectOption("chat");
    await page.evaluate(() => {
      window.savedAudioContext = window.AudioContext;
      window.savedGetUserMedia = navigator.mediaDevices.getUserMedia.bind(
        navigator.mediaDevices,
      );
      window.liveGrants = 0;
      window.liveStopped = 0;
      navigator.mediaDevices.getUserMedia = async () => {
        window.liveGrants++;
        return {
          getTracks: () => [
            { stop: () => window.liveStopped++, addEventListener: () => {} },
          ],
        };
      };
      window.AudioContext = class {
        constructor() {
          this.sampleRate = 16000;
          this.state = "running";
        }
        resume() {
          return Promise.resolve();
        }
        close() {
          this.state = "closed";
          return Promise.resolve();
        }
        createMediaStreamSource() {
          return { connect() {}, disconnect() {} };
        }
        createScriptProcessor() {
          return { connect() {}, disconnect() {} };
        }
      };
      window.feedLive = (speaking, blocks) => {
        for (let i = 0; i < blocks; i++)
          live.processor.onaudioprocess({
            inputBuffer: {
              getChannelData: () =>
                new Float32Array(320).fill(speaking ? 0.1 : 0),
            },
          });
      };
    });
    await page
      .getByRole("button", { name: "开始实时对话", exact: true })
      .click();
    await page.getByText("正在聆听，请直接说…", { exact: true }).waitFor();
    await page.evaluate(() => feedLive(false, 100));
    assert.equal(asrConnections, 0, "silence never opens ASR");
    await page.evaluate(() => feedLive(true, 20));
    await page.waitForTimeout(50);
    assert(
      await page.evaluate(() => !!live),
      "live stopped: " +
        (await page.locator("#notice").textContent()) +
        " sockets " +
        asrConnections,
    );
    await page.evaluate(() => feedLive(false, 46));
    await page
      .locator("#messages")
      .getByText("连续对话第1句", { exact: true })
      .waitFor();
    await page.waitForFunction(() => live && !live.processing, null, {
      timeout: 15000,
    });
    assert(audioBytes > 0);
    // Hold playback so the user can interrupt with a second utterance.
    await page.evaluate(() => {
      window.Audio = class {
        constructor(src) {
          this.src = src;
          this.ended = false;
        }
        play() {
          return Promise.resolve();
        }
        pause() {
          this.onpause?.();
        }
      };
      window.pendingSpeech = speak("播放中可以打断");
    });
    await page.waitForFunction(() => !!playback);
    await page.evaluate(() => feedLive(true, 20));
    await page.waitForTimeout(50);
    assert(
      await page.evaluate(() => playback === null),
      "opening speech interrupts playback",
    );
    await page.evaluate(() => {
      window.Audio = class {
        constructor(src) {
          this.src = src;
          this.ended = false;
        }
        play() {
          setTimeout(() => {
            this.ended = true;
            this.onended?.();
          }, 3);
          return Promise.resolve();
        }
        pause() {
          this.onpause?.();
        }
      };
      feedLive(false, 46);
    });
    await page
      .locator("#messages")
      .getByText("连续对话第2句", { exact: true })
      .waitFor();
    await page.waitForFunction(() => live && !live.processing, null, {
      timeout: 15000,
    });
    assert.equal(
      await page.evaluate(() => window.liveGrants),
      1,
      "microphone reused across turns",
    );
    assert.equal(finishes, 2);
    await page.evaluate(async () => {
      window.contextPlaybackCount = 0;
      live.context.decodeAudioData = async () => ({});
      live.context.createBufferSource = () => ({
        connect() {},
        disconnect() {},
        start() {
          window.contextPlaybackCount++;
          setTimeout(() => this.onended?.(), 3);
        },
        stop() {
          this.onended?.();
        },
      });
      await speak("复用手机音频通道");
    });
    assert.equal(await page.evaluate(() => window.contextPlaybackCount), 1);

    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    assert(await page.evaluate(() => live === null));
    assert.equal(await page.evaluate(() => window.liveStopped), 1);
    assert.equal(asrConnections, 2, "disconnect does not replay utterances");
    await page.evaluate(() => {
      window.agentAudioContext = window.AudioContext;
      window.agentGetUserMedia = navigator.mediaDevices.getUserMedia;
      window.AudioContext = window.savedAudioContext;
      navigator.mediaDevices.getUserMedia = window.savedGetUserMedia;
    });
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
    await page.locator("#engine").selectOption("codex");
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
    await page.locator("#speak").check();
    await page.locator("#prompt").fill("语音汇报测试");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page
      .locator("#task-detail")
      .getByRole("heading", { name: "语音汇报测试" })
      .waitFor();
    const taskId = await page.evaluate(async () => {
      const response = await fetch("/shengjian/api/v2/tasks", {
        headers: {
          Authorization:
            "Bearer " + token,
        },
      });
      return (await response.json()).tasks[0].id;
    });
    const complete = await page.request.post(
      origin + "/__test/complete/" + taskId,
    );
    assert(complete.ok());
    await page
      .locator("#task-detail")
      .getByText("已完成", { exact: true })
      .waitFor();
    for (
      let i = 0;
      i < 100 &&
      !speechBodies.some((body) => body.input === "voice-task-report");
      i++
    )
      await new Promise((resolve) => setTimeout(resolve, 25));
    assert(
      speechBodies.some((body) => body.input === "voice-task-report"),
      "completed task speaks its result",
    );
    assert(
      await page
        .locator("#task-detail")
        .getByRole("button", { name: "取消任务", exact: true })
        .isDisabled(),
    );
    await page
      .locator("#task-detail")
      .getByRole("button", { name: "停止播报", exact: true })
      .click();
    await page.evaluate(() => {
      window.agentAudio = window.Audio;
      window.Audio = window.originalAudio;
    });
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
    // Final ASR can create, inspect, continue and cancel real durable fixture tasks.
    const agentDevice = await page.evaluate(async () => (await json('/devices')).devices.find(d => d.name === '测试电脑').id);
    await page.request.post(origin + '/__test/agent-online/' + agentDevice);
    await page.evaluate(async () => {
      await refresh();
      window.AudioContext = window.agentAudioContext;
      navigator.mediaDevices.getUserMedia = window.agentGetUserMedia;
      window.Audio = window.agentAudio;
    });
    await page.getByRole('button', { name: 'Chat / Work · DeepSeek Harness', exact: true }).click();
    await page.getByRole('button', { name: '开始实时对话', exact: true }).click();
    await page.waitForFunction(() => live?.processor);
    async function sayAgent(text) {
      voiceText = text;
      await page.evaluate(() => { feedLive(false, 12); feedLive(true, 20); });
      await page.waitForTimeout(40);
      await page.evaluate(() => feedLive(false, 46));
      await page.locator('#messages').getByText(text, { exact: true }).last().waitFor();
      await page.waitForFunction(() => live && !live.processing && !busy);
    }
    await sayAgent('让电脑帮我写一份说明');
    const createdAgentTask = await page.evaluate(() => currentTask);
    assert.equal(await page.locator('#conversation').isVisible(), true);
    await page.request.post(origin + '/__test/complete/' + createdAgentTask);
    await page.locator('#messages').getByText('电脑任务已完成。voice-task-report', { exact: true }).waitFor();
    for (let i = 0; i < 100 && !speechBodies.some(body => body.input === '电脑任务已完成。voice-task-report'); i++) await page.waitForTimeout(25);
    assert(speechBodies.some(body => body.input === '电脑任务已完成。voice-task-report'));
    const countBefore = await page.evaluate(async () => (await json('/tasks')).tasks.length);
    await sayAgent('汇报进度');
    assert.equal(await page.evaluate(async () => (await json('/tasks')).tasks.length), countBefore);
    await sayAgent('继续补充示例');
    const followupTask = await page.evaluate(() => currentTask);
    assert.notEqual(followupTask, createdAgentTask);
    await sayAgent('取消当前任务');
    assert.equal(await page.evaluate(async () => (await json('/tasks/' + currentTask)).task.state), 'cancelled');
    await page.evaluate(() => stopLive());
    await page.getByRole('button', { name: 'Chat / Work · DeepSeek Harness', exact: true }).click();
    voiceText = null;
    await page.evaluate(() => { window.AudioContext = window.savedAudioContext; navigator.mediaDevices.getUserMedia = window.savedGetUserMedia; window.Audio = window.originalAudio; });
    // A response begun under the old account must never appear after logout.
    let releaseReply, markStarted;
    const replyGate = new Promise((resolve) => (releaseReply = resolve));
    const requestStarted = new Promise((resolve) => (markStarted = resolve));
    await page.route(
      "**/shengjian/api/v2/assistant/chat",
      async (route) => {
        markStarted();
        await replyGate;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            action: "status", reply: "private-old-reply",
          }),
        });
      },
    );
    await page.locator("#destination").selectOption("chat");
    await page.locator("#prompt").fill("旧账号延迟请求");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await requestStarted;
    await page.getByRole("button", { name: "退出登录" }).click();
    await page.locator("#auth").waitFor({ state: "visible" });
    await page.getByLabel("用户名", { exact: true }).fill("browser-second");
    await page.getByLabel("密码", { exact: true }).fill("browser-password-456");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator("#workspace").waitFor({ state: "visible" });
    releaseReply();
    await page.waitForTimeout(200);
    assert.equal(await page.locator("#messages").textContent(), "");
    assert.equal(await page.locator("#prompt").inputValue(), "");
    assert.equal(await page.locator("#task-list").textContent(), "");
    assert.equal(await page.locator("#device-config").textContent(), "");
    assert(
      !(await page
        .getByRole("button", { name: "发送", exact: true })
        .isDisabled()),
    );
    await page.getByRole("button", { name: "任务", exact: true }).click();
    assert(
      !(await page.locator("#task-detail").textContent()).includes(
        "voice-task-report",
      ),
    );
    assert.deepEqual(errors, []);
    // Scan on another device, close/reopen, then revoke that device from desktop.
    const ticket = await page.evaluate(async () => (await json('/auth/qr', {})).ticket);
    let phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    let phone = await phoneContext.newPage();
    await phone.goto(origin + '/shengjian/api/v2/console#login=' + ticket);
    await phone.locator('#workspace').waitFor({ state: 'visible' });
    assert.equal(new URL(phone.url()).hash, '');
    assert.equal(await phone.evaluate(() => sessionStorage.getItem('shengjian.session')), null);
    const phoneDevice = await page.evaluate(async () => (await json('/devices')).devices.find(d => d.name === '手机扫码登录').id);
    const saved = await phoneContext.storageState();
    await phoneContext.close();
    phoneContext = await browser.newContext({ storageState: saved });
    phone = await phoneContext.newPage();
    await phone.goto(origin + '/shengjian/api/v2/console');
    await phone.locator('#workspace').waitFor({ state: 'visible' });
    await page.evaluate(async id => json('/devices/' + id, undefined, 'DELETE'), phoneDevice);
    await phone.reload();
    await phone.locator('#auth').waitFor({ state: 'visible' });
    await phone.goto(origin + '/shengjian/api/v2/console#login=' + ticket);
    await phone.getByText('二维码已使用或已过期，请在电脑上刷新后重新扫描。', { exact: true }).waitFor();
    await phoneContext.close();
    await page.getByRole("button", { name: "退出登录" }).click();
    console.log(
      "Core UI: QR redeem/replay/restart/revocation, real-time endpointing/two turns/interruption/mic reuse/offline, account isolation, voice queue/stop, task report, enrollment/grants, cancellation, light/dark and mobile passed",
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
