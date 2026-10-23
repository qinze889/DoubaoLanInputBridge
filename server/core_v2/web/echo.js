// A conservative residual-echo guard, in addition to browser acoustic AEC.
// Only correlates against this page's actual scheduled PCM. Uncertain/double-talk
// frames remain audible to the recognizer; silence is never used as a blanket lockout.
class PlaybackEchoGuard {
  constructor() {
    this.rate = 16000;
    this.size = this.rate * 8;
    this.reference = new Float32Array(this.size);
    this.tags = new Int32Array(this.size).fill(-1);
    this.history = new Float32Array(0);
    this.lastEnd = null;
    this.latest = -1;
    this.noise = 0.001;
    this.last = { suppressed: false, correlation: 0 };
  }
  add(values, start, rate = 24000) {
    const count = Math.floor((values.length * this.rate) / rate);
    const begin = Math.round(start * this.rate);
    for (let i = 0; i < count; i++) {
      const pos = (i * rate) / this.rate,
        low = Math.floor(pos),
        fraction = pos - low;
      const value =
        values[low] * (1 - fraction) +
        values[Math.min(low + 1, values.length - 1)] * fraction;
      const at = begin + i,
        index = ((at % this.size) + this.size) % this.size;
      this.reference[index] = value;
      this.tags[index] = at;
    }
    this.latest = Math.max(this.latest, begin + count);
  }
  sample(at) {
    if (at < 0) return 0;
    const index = at % this.size;
    return this.tags[index] === at ? this.reference[index] : 0;
  }
  cut(time) {
    // Keep the already-played reference for acoustic tails after interruption.
    const begin = Math.max(0, Math.round(time * this.rate)),
      end = Math.min(this.latest, begin + this.size);
    for (let at = begin; at < end; at++) {
      const index = at % this.size;
      if (this.tags[index] === at) this.tags[index] = -1;
    }
    this.latest = begin;
  }
  process(pcm, endTime) {
    const end = Math.round(endTime * this.rate),
      begin = end - pcm.length;
    if (this.lastEnd !== null && Math.abs(begin - this.lastEnd) > 160)
      this.history = new Float32Array(0);
    this.lastEnd = end;
    const current = Float32Array.from(pcm, (x) => x / 32768),
      all = new Float32Array(this.history.length + current.length);
    all.set(this.history);
    all.set(current, this.history.length);
    this.history = all.slice(Math.max(0, all.length - 1280));
    let energy = 0;
    for (const x of current) energy += x * x;
    const rms = Math.sqrt(energy / Math.max(1, current.length));
    this.last = { suppressed: false, correlation: 0 };
    if (end - this.latest > 6400 || this.latest < 0) {
      if (rms < 0.01) this.noise = 0.98 * this.noise + 0.02 * rms;
      return pcm;
    }
    if (this.history.length < 640 || rms < 0.002) return pcm;
    const history = this.history,
      start = end - history.length;
    function fit(guard, lag, step) {
      let xy = 0,
        xx = 0,
        yy = 0;
      // High-pass both signals before matching; shared pitch alone is insufficient.
      for (let i = 8; i < history.length; i += step) {
        const x = history[i] - 0.8 * history[i - 8];
        const y =
          guard.sample(start + i - lag) -
          0.8 * guard.sample(start + i - 8 - lag);
        xy += x * y;
        xx += x * x;
        yy += y * y;
      }
      return { score: xx > 1e-8 && yy > 1e-8 ? (xy * xy) / (xx * yy) : 0, lag };
    }
    let best = { score: 0, lag: 0 };
    for (let lag = 0; lag <= 4800; lag += 16) {
      const value = fit(this, lag, 8);
      if (value.score > best.score) best = value;
    }
    if (best.score < 0.72) return pcm;
    const coarse = best.lag;
    for (let lag = Math.max(0, coarse - 16); lag <= coarse + 16; lag++) {
      const value = fit(this, lag, 4);
      if (value.score > best.score) best = value;
    }
    this.last.correlation = Math.sqrt(best.score);
    if (best.score < 0.8) return pcm;
    let xy = 0,
      yy = 0;
    for (let i = 0; i < current.length; i++) {
      const y = this.sample(begin + i - best.lag);
      xy += current[i] * y;
      yy += y * y;
    }
    if (yy < 1e-7) return pcm;
    const gain = Math.max(-3, Math.min(3, xy / yy));
    const residual = new Float32Array(current.length);
    let residualEnergy = 0;
    for (let i = 0; i < current.length; i++) {
      const x = current[i] - gain * this.sample(begin + i - best.lag);
      residual[i] = x;
      residualEnergy += x * x;
    }
    const residualRms = Math.sqrt(residualEnergy / current.length);
    // Do not erase a near-end speaker mixed with echo. Only suppress at noise floor.
    if (
      residualRms <= Math.max(0.003, this.noise * 2.5) &&
      residualRms < rms * 0.4
    ) {
      this.last.suppressed = true;
      return new Int16Array(pcm.length);
    }
    if (residualRms < rms * 0.8)
      return Int16Array.from(residual, (x) =>
        Math.max(-32768, Math.min(32767, Math.round(x * 32768))),
      );
    return pcm;
  }
}
if (typeof module !== "undefined") module.exports = PlaybackEchoGuard;
