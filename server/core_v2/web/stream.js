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
    this.timer = null;
  }
  push(text) {
    this.pending += text;
    while (this.pending) {
      const minimum = this.first ? 4 : 18;
      const punctuation = /[。！？!?；;\n，,]/g;
      let match,
        cut = 0;
      while ((match = punctuation.exec(this.pending))) {
        if (match.index + 1 >= minimum) {
          cut = match.index + 1;
          break;
        }
      }
      const maximum = this.first ? 12 : 64;
      if (!cut && Array.from(this.pending).length >= maximum)
        cut = Array.from(this.pending).slice(0, maximum).join("").length;
      if (!cut) {
        if (this.first && this.pending.length >= 4 && !this.timer)
          this.timer = setTimeout(() => {
            this.timer = null;
            if (this.first) this.flush();
          }, 80);
        return;
      }
      const piece = this.pending.slice(0, cut);
      this.pending = this.pending.slice(cut);
      this.first = false;
      clearTimeout(this.timer);
      this.timer = null;
      this.send(piece);
    }
  }
  cancel() {
    clearTimeout(this.timer);
    this.timer = null;
    this.pending = "";
  }
  flush() {
    clearTimeout(this.timer);
    this.timer = null;
    this.first = false;
    if (this.pending.trim()) this.send(this.pending);
    this.pending = "";
  }
}
// Keep the reconstruction filter's history across network packets. Letting each
// AudioBufferSource resample an isolated 24 kHz packet creates edge transients.
class PCMRateConverter {
  constructor(rate) {
    this.rate = rate;
    this.step = 24000 / rate;
    this.reset();
    const cutoff = Math.min(1, rate / 24000) * 0.94;
    this.filters = Array.from({ length: 1024 }, (_, phase) => {
      const weights = new Float64Array(32);
      let sum = 0;
      for (let j = 0; j < 32; j++) {
        const x = j - 15 - phase / 1024;
        const sinc = Math.abs(x) < 1e-9 ? cutoff : Math.sin(Math.PI * cutoff * x) / (Math.PI * x);
        weights[j] = sinc * (0.5 + 0.5 * Math.cos(Math.PI * x / 16));
        sum += weights[j];
      }
      return weights.map((value) => value / sum);
    });
  }
  reset() {
    this.input = new Float32Array(0);
    this.offset = this.received = this.emitted = 0;
  }
  push(values, final = false) {
    const joined = new Float32Array(this.input.length + values.length);
    joined.set(this.input);
    joined.set(values, this.input.length);
    this.input = joined;
    this.received += values.length;
    const end = final ? Math.ceil(this.received / this.step) : Math.max(0, Math.ceil((this.received - 16) / this.step));
    const output = new Float32Array(Math.max(0, end - this.emitted));
    for (let i = 0; i < output.length; i++, this.emitted++) {
      const position = this.emitted * this.step, center = Math.floor(position);
      const filter = this.filters[Math.min(1023, Math.floor((position - center) * 1024))];
      let value = 0;
      for (let j = 0; j < 32; j++) value += (this.input[center + j - 15 - this.offset] || 0) * filter[j];
      output[i] = value;
    }
    const keep = Math.max(0, Math.floor(this.emitted * this.step) - 15 - this.offset);
    this.input = this.input.slice(keep);
    this.offset += keep;
    return output;
  }
}
class PCMPlayback {
  constructor(context, onStart = () => {}, echo = null) {
    this.context = context;
    this.sources = new Set();
    this.next = 0;
    this.stopped = false;
    this.tail = null;
    this.src = "";
    this.onStart = onStart;
    this.echo = echo;
    this.segments = [];
    this.rate = context.sampleRate || 24000;
    this.converter = new PCMRateConverter(this.rate);
  }
  async running() {
    if(this.stopped)return false;
    if(this.context.state==='closed')throw new Error('audio_context_closed');
    if(['suspended','interrupted'].includes(this.context.state)){
      let timer;
      try{
        await Promise.race([this.context.resume(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('audio_context_paused')),1800);})]);
        if(!this.stopped&&this.context.state!=='running')throw new Error('audio_context_paused');
      }finally{clearTimeout(timer);}
    }
    return !this.stopped;
  }
  async push(encoded) {
    if(!await this.running())return;
    // Wait at most two seconds ahead; a long answer cannot accumulate minutes of audio.
    while (!this.stopped && this.next - this.context.currentTime > 2){
      if(!await this.running())return;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
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
    const values = new Float32Array(count);
    const view = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
    for (let i = 0; i < count; i++)
      values[i] = view.getInt16(i * 2, true) / 32768;
    this.schedule(this.converter.push(values));
  }
  schedule(values) {
    if (this.stopped || !values.length) return;
    const buffer = this.context.createBuffer(1, values.length, this.rate);
    buffer.getChannelData(0).set(values);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    source.onended = () => {
      this.sources.delete(source);
      try{source.disconnect();}catch{}
    };
    this.sources.add(source);
    // A small initial jitter cushion; do not insert a fresh safety gap into
    // every packet that arrives less than 25 ms before its scheduled boundary.
    const now = this.context.currentTime;
    const at = this.next >= now + 0.005 ? this.next : now + 0.06;
    this.next = at + buffer.duration;
    this.echo?.add(values, at, this.rate);
    source.start(at);
    if (this.firstScheduled === undefined) this.firstScheduled = at;
    this.onStart();
  }
  async drain() {
    this.finishSegment();
    while (!this.stopped && this.sources.size){
      if(!await this.running())return;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  }
  mark(text, start) {
    this.finishSegment();
    this.segments.push({ text, start, end: this.next });
  }
  finishSegment() {
    if (!this.converter.received || this.stopped) return;
    this.schedule(this.converter.push(new Float32Array(0), true));
    this.converter.reset();
  }
  heard() {
    return this.segments
      .filter((segment) => segment.end <= this.context.currentTime)
      .map((segment) => segment.text)
      .join("");
  }
  pause() {
    this.onStop?.();
    this.echo?.cut(this.context.currentTime);
    this.stopped = true;
    for (const source of this.sources) {
      try{source.stop();}catch{}
      try{source.disconnect();}catch{}
    }
    this.sources.clear();
    this.tail = null;
    this.converter.reset();
  }
}
if (typeof module !== "undefined")
  module.exports = { readEvents, VoiceSentences, PCMPlayback, PCMRateConverter };
