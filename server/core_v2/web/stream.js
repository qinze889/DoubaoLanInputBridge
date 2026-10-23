// Incremental parsers and bounded PCM playback; usable without a browser in tests.
async function readEvents(response, format, onEvent, signal) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "",
    eventLines = [];
  async function line(raw) {
    raw = raw.replace(/\r$/, "");
    if (format === "sse") {
      if (raw.startsWith("data:")) eventLines.push(raw.slice(5).trimStart());
      else if (!raw && eventLines.length) {
        const data = eventLines.join("\n");
        eventLines = [];
        await onEvent(data === "[DONE]" ? { done: true } : JSON.parse(data));
      }
    } else if (raw) await onEvent(JSON.parse(raw));
  }
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      if (pending.length > 256 * 1024) throw new Error("流式响应超过限制");
      let index;
      while ((index = pending.indexOf("\n")) >= 0) {
        await line(pending.slice(0, index));
        pending = pending.slice(index + 1);
      }
      if (done) {
        if (pending) await line(pending);
        if (format === "sse") await line("");
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
class VoiceSentences {
  constructor(send) {
    this.send = send;
    this.pending = "";
    this.first = true;
  }
  push(text) {
    this.pending += text;
    while (this.pending) {
      const minimum = this.first ? 8 : 18;
      const punctuation = /[。！？!?；;\n，,]/g;
      let match,
        cut = 0;
      while ((match = punctuation.exec(this.pending))) {
        if (match.index + 1 >= minimum) {
          cut = match.index + 1;
          break;
        }
      }
      if (!cut && Array.from(this.pending).length >= 64)
        cut = Array.from(this.pending).slice(0, 64).join("").length;
      if (!cut) return;
      const piece = this.pending.slice(0, cut);
      this.pending = this.pending.slice(cut);
      this.first = false;
      this.send(piece);
    }
  }
  flush() {
    if (this.pending.trim()) this.send(this.pending);
    this.pending = "";
  }
}
class PCMPlayback {
  constructor(context, onStart = () => {}) {
    this.context = context;
    this.sources = new Set();
    this.next = 0;
    this.stopped = false;
    this.tail = null;
    this.src = "";
    this.onStart = onStart;
  }
  async push(encoded) {
    // Wait at most two seconds ahead; a long answer cannot accumulate minutes of audio.
    while (!this.stopped && this.next - this.context.currentTime > 2)
      await new Promise((resolve) => setTimeout(resolve, 20));
    if (this.stopped) return;
    let bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    if (this.tail !== null) {
      const joined = new Uint8Array(bytes.length + 1);
      joined[0] = this.tail;
      joined.set(bytes, 1);
      bytes = joined;
    }
    this.tail = bytes.length % 2 ? bytes[bytes.length - 1] : null;
    const count = Math.floor(bytes.length / 2);
    if (!count) return;
    const buffer = this.context.createBuffer(1, count, 24000),
      values = buffer.getChannelData(0);
    const view = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
    for (let i = 0; i < count; i++)
      values[i] = view.getInt16(i * 2, true) / 32768;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
    };
    this.sources.add(source);
    const at = Math.max(this.next, this.context.currentTime + 0.025);
    this.next = at + buffer.duration;
    source.start(at);
    this.onStart();
  }
  async drain() {
    while (!this.stopped && this.sources.size)
      await new Promise((resolve) => setTimeout(resolve, 20));
  }
  pause() {
    this.stopped = true;
    for (const source of this.sources) {
      source.stop();
      source.disconnect();
    }
    this.sources.clear();
  }
}
if (typeof module !== "undefined")
  module.exports = { readEvents, VoiceSentences, PCMPlayback };
