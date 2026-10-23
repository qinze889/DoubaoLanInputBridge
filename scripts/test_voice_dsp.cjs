const assert = require("node:assert/strict");
const Echo = require("../server/core_v2/web/echo.js");
const VAD = require("../server/core_v2/web/vad.js");
const {
  VoiceSentences,
  PCMPlayback,
} = require("../server/core_v2/web/stream.js");
(async () => {
  const rate = 16000,
    length = rate * 3;
  let seed = 71,
    state = 0;
  const voice = Float32Array.from({ length }, (_, i) => {
    seed = (Math.imul(seed, 1664525) + 1013904223) | 0;
    state = 0.7 * state + 0.3 * (seed / 2147483648);
    return (
      state * 0.3 * (0.6 + 0.4 * Math.sin(i / 2370)) +
      0.04 * Math.sin(i * 0.047) * Math.sin(i * 0.013)
    );
  });
  for (const delayMs of [24, 87, 203]) {
    const guard = new Echo();
    guard.add(voice, 0, rate);
    let starts = 0,
      suppressed = 0;
    const vad = new VAD({ start: () => starts++, data() {}, end() {} });
    const lag = Math.round((delayMs * rate) / 1000);
    for (let start = 0; start < length; start += 320) {
      const pcm = Int16Array.from({ length: 320 }, (_, j) =>
        Math.round((voice[start + j - lag] || 0) * 0.45 * 32768),
      );
      const clean = guard.process(pcm, (start + 320) / rate);
      if (guard.last.suppressed) suppressed++;
      vad.push(clean);
    }
    assert(suppressed > 100, "delayed playback echo is detected");
    assert.equal(starts, 0, "playback echo must not start a new turn");
    // Independent near-end voice mixed with echo must still interrupt.
    let userStarts = 0;
    const nearVAD = new VAD({ start: () => userStarts++, data() {}, end() {} });
    for (let start = 0; start < rate; start += 320) {
      const pcm = Int16Array.from({ length: 320 }, (_, j) => {
        const i = start + j;
        const near =
          0.09 * Math.sin(i * 0.163) * (1 + 0.2 * Math.sin(i * 0.006));
        return Math.round(((voice[i - lag] || 0) * 0.45 + near) * 32768);
      });
      nearVAD.push(guard.process(pcm, (start + 320) / rate));
    }
    assert(userStarts > 0, "double-talk preserves the near-end speaker");
  }
  const guard = new Echo();
  guard.add(voice, 0, rate);
  guard.cut(0.5);
  assert(
    guard.sample(7000) !== 0 && guard.sample(9000) === 0,
    "interruption clears future audio but retains played tail",
  );
  const tail = new Echo();
  tail.add(voice, 0, rate);
  tail.cut(0.5);
  let tailStarts = 0;
  const tailVAD = new VAD({ start: () => tailStarts++, data() {}, end() {} });
  const lag = 1600;
  for (let start = 6400; start < 12800; start += 320) {
    const pcm = Int16Array.from({ length: 320 }, (_, j) =>
      Math.round(
        (start + j - lag < 8000 ? voice[start + j - lag] || 0 : 0) *
          0.45 *
          32768,
      ),
    );
    tailVAD.push(tail.process(pcm, (start + 320) / rate));
  }
  assert.equal(
    tailStarts,
    0,
    "played acoustic tail after interruption does not trigger another turn",
  );
  const heardPlayer = new PCMPlayback({ currentTime: 2 });
  heardPlayer.segments = [
    { text: "已经播完。", start: 0, end: 1 },
    { text: "尚未播出。", start: 1, end: 3 },
  ];
  assert.equal(heardPlayer.heard(), "已经播完。");
  const pieces = [];
  const sentences = new VoiceSentences((text) => pieces.push(text));
  sentences.push("这段开头没有标点");
  await new Promise((r) => setTimeout(r, 180));
  assert.equal(
    pieces[0],
    "这段开头没有标点",
    "short first phrase does not wait for the next model token",
  );
  const cancelled = [];
  const stopped = new VoiceSentences((text) => cancelled.push(text));
  stopped.push("这是还没有标点");
  stopped.cancel();
  await new Promise((r) => setTimeout(r, 180));
  assert.deepEqual(cancelled, []);
  console.log(
    "Voice DSP: delayed echo, double-talk, interruption tail, heard-only history and timed first phrase passed",
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
