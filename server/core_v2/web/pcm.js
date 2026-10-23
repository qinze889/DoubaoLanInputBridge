class PCMResampler {
  constructor(rate) {
    this.ratio = rate / 16000;
    this.pending = new Float32Array(0);
    this.position = 0;
  }
  push(samples) {
    const data = new Float32Array(this.pending.length + samples.length);
    data.set(this.pending);
    data.set(samples, this.pending.length);
    const output = [];
    let position = this.position;
    while (position + 1 < data.length) {
      const index = Math.floor(position),
        fraction = position - index;
      const sample = data[index] * (1 - fraction) + data[index + 1] * fraction;
      output.push(
        Math.max(-1, Math.min(1, sample)) * (sample < 0 ? 32768 : 32767),
      );
      position += this.ratio;
    }
    const consumed = Math.min(
      Math.floor(position),
      Math.max(0, data.length - 1),
    );
    this.pending = data.slice(consumed);
    this.position = position - consumed;
    return Int16Array.from(output);
  }
}

if (typeof module !== "undefined") module.exports = PCMResampler;
