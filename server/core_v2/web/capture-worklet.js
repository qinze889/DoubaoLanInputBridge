// Microphone capture runs on the render thread, independent of UI work.
class ShengjianCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Float32Array(512);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel)
      for (let i = 0; i < channel.length; i++) {
        this.samples[this.offset++] = channel[i];
        if (this.offset === this.samples.length) {
          this.port.postMessage(this.samples, [this.samples.buffer]);
          this.samples = new Float32Array(512);
          this.offset = 0;
        }
      }
    return true;
  }
}
registerProcessor("shengjian-capture", ShengjianCapture);
