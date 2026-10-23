// Local 16 kHz endpoint detector. No browser speech service or microphone upload in silence.
class VoiceEndpoint {
  constructor({ start, data, end }) {
    this.callbacks = { start, data, end };
    this.reset();
  }
  reset() {
    this.pre = [];
    this.preLength = 0;
    this.active = false;
    this.voiced = 0;
    this.silence = 0;
    this.length = 0;
    this.noise = 0.002;
  }
  push(pcm) {
    let power = 0;
    for (const value of pcm) power += (value / 32768) ** 2;
    const rms = Math.sqrt(power / Math.max(1, pcm.length));
    const voice = rms > Math.max(0.012, this.noise * 3.5);
    if (!this.active) {
      if (!voice) this.noise = this.noise * 0.98 + rms * 0.02;
      this.pre.push(pcm.slice());
      this.preLength += pcm.length;
      while (this.preLength > 6400 && this.pre.length > 1)
        this.preLength -= this.pre.shift().length;
      this.voiced = voice ? this.voiced + pcm.length : 0;
      if (this.voiced < 2880) return; // 180 ms prevents a click from opening ASR.
      this.active = true;
      this.length = this.preLength;
      this.callbacks.start(this.pre);
      this.pre = [];
      this.preLength = 0;
      return;
    }
    this.length += pcm.length;
    this.silence = voice ? 0 : this.silence + pcm.length;
    this.callbacks.data(pcm);
    if (this.silence >= 14400 || this.length >= 25 * 16000) {
      this.reset();
      this.callbacks.end();
    }
  }
}
if (typeof module !== "undefined") module.exports = VoiceEndpoint;
