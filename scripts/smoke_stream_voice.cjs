const { chromium } = require("../desktop/node_modules/playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
const {
  readEvents,
  VoiceSentences,
} = require("../server/core_v2/web/stream.js");
(async () => {
  // UTF-8 and SSE records may split at any byte, including inside Chinese text.
  const wire = new TextEncoder().encode(
    'data: {"choices":[{"delta":{"content":"你好。"}}]}\r\n\r\ndata: [DONE]\n\n',
  );
  const output = [];
  await readEvents(
    new Response(
      new ReadableStream({
        start(c) {
          for (const byte of wire) c.enqueue(Uint8Array.of(byte));
          c.close();
        },
      }),
    ),
    "sse",
    (event) => output.push(event),
  );
  assert.equal(output[0].choices[0].delta.content, "你好。");
  assert(output[1].done);
  const combined=Array.from({length:400},()=>JSON.stringify({type:'audio.chunk',data:'a'.repeat(800)})+'\n').join('');
  let coalesced=0;
  await readEvents(new Response(combined),'ndjson',()=>coalesced++);
  assert.equal(coalesced,400,'a large network read may contain many valid small audio records');
  await assert.rejects(()=>readEvents(new Response(JSON.stringify({data:'a'.repeat(300000)})+'\n'),'ndjson',()=>{}),/voice_stream_invalid/);
  const sentences = [];
  const segmenter = new VoiceSentences((text) => sentences.push(text));
  segmenter.push("这是第一句实时回答。后续内容");
  assert.equal(sentences[0], "这是第一句实时回答。");
  segmenter.flush();
  assert.equal(sentences[1], "后续内容");
  for (const text of ['长'.repeat(2500)+'。', '😀'.repeat(140)+'，后续回答。']) {
    const chunks=[];
    const bounded=new VoiceSentences(part=>chunks.push(part));
    bounded.push(text);bounded.flush();
    assert.equal(chunks.join(''),text,'long complete answers keep every character');
    assert(Array.from(chunks[0]).length<=12,'first punctuation cannot bypass first-audio segment limit');
    assert(chunks.every(part=>Array.from(part).length<=64),'long sentences stay within TTS segment limit');
    assert(chunks.every(part=>part.isWellFormed()),'never split Unicode surrogate pairs');
  }
  const directory = fs.mkdtempSync(
    path.join(os.tmpdir(), "shengjian-stream-ui-"),
  );
  const port = 18782,
    origin = `http://127.0.0.1:${port}`;
  const server = spawn(
    process.env.SHENGJIAN_TEST_PYTHON || path.resolve(".venv/bin/python"),
    ["tests/fixtures/core_ui_server.py", directory, String(port)],
    {
      env: { ...process.env, SHENGJIAN_FIXTURE_STREAM: "1", SHENGJIAN_FIXTURE_HARNESS: "1" },
      stdio: ["ignore", "ignore", "pipe"],
    },
  );
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try {
        if ((await fetch(origin + "/shengjian/api/v2/health")).ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    assert(ready);
    browser = await chromium.launch({
      headless: true,
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
      ...(process.env.SHENGJIAN_UI_BROWSER
        ? { executablePath: process.env.SHENGJIAN_UI_BROWSER }
        : {}),
    });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let connections = 0,
      finals = 0,
      finalDelay = 0;
    await page.routeWebSocket(/\/voice\/asr\/stream$/, (socket) => {
      connections++;
      socket.onMessage((data) => {
        if (typeof data === "string") {
          const control = JSON.parse(data);
          if (control.token)
            socket.send(
              JSON.stringify({ type: "asr.ready", partial_results: true }),
            );
          if (control.type === "finish") {
            const number = ++finals;
            const complete = () => {
              socket.send(
                JSON.stringify({
                  type: "asr.final",
                  text: "这是第" + number + "个语音问题",
                }),
              );
              socket.send(JSON.stringify({ type: "asr.finished" }));
            };
            if (finalDelay) setTimeout(complete, finalDelay);
            else complete();
          }
        } else
          socket.send(
            JSON.stringify({ type: "asr.partial", text: "实时识别的中间文字" }),
          );
      });
    });
    await page.goto(origin + "/shengjian/api/v2/console");
    await page.getByLabel("用户名", { exact: true }).fill("browser-test");
    await page.getByLabel("密码", { exact: true }).fill("browser-password-123");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator("#workspace").waitFor({ state: "visible" });
    await page.evaluate(async()=>{const d=await json('/devices',{name:'Fixture Harness',capabilities:['tasks']});await json('/devices/'+d.id,{grants:['tasks']},'PATCH');await fetch('/__test/agent-online/'+d.id,{method:'POST'});await refresh();});
    await page.evaluate(() => {
      window.grants = 0;
      window.audioStarts = 0;
      window.audioStops = 0;
      navigator.mediaDevices.getUserMedia = async () => {
        window.grants++;
        return { getTracks: () => [{ stop() {}, addEventListener() {} }] };
      };
      window.AudioContext = class {
        constructor() {
          this.sampleRate = 16000;
          this.state = "running";
          this.started = performance.now();
        }
        get currentTime() {
          return (performance.now() - this.started) / 1000;
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
        createBuffer(channels, length, rate) {
          return {
            duration: length / rate,
            getChannelData: () => new Float32Array(length),
          };
        }
        createBufferSource() {
          const context = this;
          return {
            connect() {},
            disconnect() {},
            start(at) {
              window.audioStarts++;
              window.firstAudioAt ??= performance.now();
              this.timer = setTimeout(
                () => this.onended?.(),
                Math.max(0, (at - context.currentTime) * 1000) +
                  this.buffer.duration * 1000,
              );
            },
            stop() {
              window.audioStops++;
              clearTimeout(this.timer);
              this.onended?.();
            },
          };
        }
      };
      window.feed = (voice, n) => {
        for (let i = 0; i < n; i++)
          live.processor.onaudioprocess({
            inputBuffer: {
              getChannelData: () => new Float32Array(320).fill(voice ? 0.1 : 0),
            },
          });
      };
    });
    await page
      .getByRole("button", { name: "开始实时对话", exact: true })
      .click();
    await page
      .getByText("正在聆听 · 实时识别，可随时打断", { exact: true })
      .waitFor();
    await page.evaluate(() => feed(true, 20));
    await page
      .locator("#live-transcript")
      .getByText("实时识别的中间文字", { exact: true })
      .waitFor();
    assert.equal(
      finals,
      0,
      "partial transcript is visible before end of speech",
    );
    assert(
      await page.evaluate(() => live.utterance.earlySamples > 0),
      "captured onset is sent after auth without waiting for the ready round trip",
    );
    await page.evaluate(() => feed(false, 40));
    await page.waitForFunction(() => window.audioStarts > 0);
    const partialReply = await page
      .locator("#messages .assistant")
      .last()
      .textContent();
    assert.equal(
      partialReply,
      "这是第一句实时回答。",
      "first audio plays before the rest of model generation",
    );
    await page.evaluate(() => {
      window.oldTurn = replyController;
      window.oldPlayer = playback;
      feed(true, 20);
    });
    await page.waitForTimeout(50);
    assert(
      await page.evaluate(() => oldTurn.signal.aborted),
      "barge-in detaches reply without cancelling background work",
    );
    assert(
      await page.evaluate(() => oldPlayer.stopped),
      "barge-in clears scheduled PCM",
    );
    assert(await page.evaluate(() => window.audioStops > 0));
    await page.evaluate(() => feed(false, 40));
    await page.waitForFunction(() => live && !live.processing, null, {
      timeout: 15000,
    });
    assert.equal(finals, 2);
    assert.equal(await page.evaluate(() => window.grants), 1);
    assert.equal(await page.locator("#messages .assistant").count(), 2);
    assert.equal(
      await page.locator("#messages .assistant").first().textContent(),
      "这是第一句实时回答。",
      "late deltas from the interrupted turn are ignored",
    );
    const historyAfterBarge = await page.evaluate(() => messages);
    assert(
      historyAfterBarge.some(
        (m) => m.role === "assistant" && m.content.includes("后续内容未播出"),
      ),
      "next turn knows the previous voice reply was interrupted",
    );
    const userCount = await page.locator("#messages .user").count();
    finalDelay = 300;
    await page.evaluate(() => feed(true, 20));
    await page.waitForTimeout(30);
    await page.evaluate(() => feed(false, 40));
    await page.evaluate(() => feed(true, 20));
    assert(
      await page.evaluate(() => !!live.waitingFor),
      "a resumed phrase waits for the earlier ASR final",
    );
    finalDelay = 0;
    await page.waitForFunction(
      () => live.utterance.ready && !live.waitingFor,
      null,
      { timeout: 5000 },
    );
    await page.evaluate(() => {
      clearInterval(refreshTimer);
      window.savedRefresh = refresh;
      const gate = new Promise((resolve) => (window.finishReply = resolve));
      refresh = async () => {
        window.finishingReply = true;
        await gate;
        return window.savedRefresh();
      };
    });
    await page.evaluate(() => feed(false, 40));
    await page.waitForFunction(() => window.finishingReply);
    await page.evaluate(() => feed(true, 3)); // first 60 ms of the next speaker
    await page.evaluate(() => {
      refresh = window.savedRefresh;
      window.finishReply();
    });
    await page.waitForFunction(() => live && !live.processing, null, {
      timeout: 15000,
    });
    assert(
      await page.evaluate(() => live.detector.voiced >= 960),
      "reply completion preserves a new speaker's onset",
    );
    assert.equal(
      await page.locator("#messages .user").count(),
      userCount + 1,
      "continuation submits exactly once",
    );
    assert.equal(
      await page.locator("#messages .user").last().textContent(),
      "这是第3个语音问题 这是第4个语音问题",
      "no dropped words across the ASR finish boundary",
    );
    await page.evaluate(() => feed(true, 3));
    await page.waitForFunction(
      () => live.utterance.ready && !live.utterance.final,
    );
    await page.evaluate(() => feed(false, 40));
    await page.waitForFunction(() => live && !live.processing, null, {
      timeout: 15000,
    });
    // Listening also remains active while waiting for the model, before any audio.
    await page.evaluate(() => feed(true, 20));
    await page.waitForTimeout(30);
    await page.evaluate(() => feed(false, 40));
    await page.waitForFunction(() => !!replyController);
    await page.evaluate(() => {
      window.thinkingTurn = replyController;
      feed(true, 20);
    });
    assert(await page.evaluate(() => thinkingTurn.signal.aborted));
    await page
      .getByRole("button", { name: "结束实时对话", exact: true })
      .click();
    await page.waitForTimeout(200);
    assert(await page.evaluate(() => live === null && playback === null));
    // Native AudioWorklet path: fake hardware, real browser audio graph and CSP.
    const workletPage = await page.context().newPage();
    let captured = 0;
    workletPage.on("pageerror", (e) => errors.push(e.message));
    await workletPage.routeWebSocket(/\/voice\/asr\/stream$/, (socket) => {
      socket.onMessage((data) => {
        if (typeof data === "string") {
          if (JSON.parse(data).token)
            socket.send(
              JSON.stringify({ type: "asr.ready", partial_results: true }),
            );
        } else captured += data.length;
      });
    });
    await workletPage.bringToFront();
    await workletPage.goto(origin + "/shengjian/api/v2/console");
    // A new tab restores the HttpOnly persistent session without another login.
    await workletPage.locator("#workspace").waitFor({ state: "visible" });
    await workletPage
      .getByRole("button", { name: "开始实时对话", exact: true })
      .click();
    await workletPage.waitForFunction(
      () => live?.processor instanceof AudioWorkletNode,
      null,
      { timeout: 10000 },
    );
    await workletPage.evaluate(() => {
      const oscillator = live.context.createOscillator(),
        gain = live.context.createGain();
      gain.gain.value = 0.1;
      oscillator.connect(gain);
      gain.connect(live.processor);
      oscillator.start();
    });
    for (let i = 0; i < 100 && !captured; i++)
      await new Promise((resolve) => setTimeout(resolve, 100));
    assert(
      captured > 0,
      "real AudioWorklet captures and resamples the browser audio graph",
    );
    await workletPage
      .getByRole("button", { name: "结束实时对话", exact: true })
      .click();
    assert(await workletPage.evaluate(() => live === null));
    await workletPage.close();
    assert.deepEqual(errors, []);
    console.log(
      "Streaming voice UI: incremental UTF-8/SSE, partial ASR, audio before model completion, barge-in during generation/playback/thinking, no stale audio or text, microphone reuse passed",
    );
  } finally {
    if (browser) await browser.close();
    server.kill("SIGTERM");
    await new Promise((r) =>
      server.exitCode !== null ? r() : server.once("exit", r),
    );
    fs.rmSync(directory, { recursive: true, force: true });
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
