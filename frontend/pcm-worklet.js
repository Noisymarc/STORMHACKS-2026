// Downsamples mic audio to 16 kHz mono s16le and posts ~250 ms chunks.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.out = [];
  }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (; this.pos < ch.length; this.pos += this.ratio) {
      const i = Math.floor(this.pos);
      const f = this.pos - i;
      const next = ch[Math.min(i + 1, ch.length - 1)];
      this.out.push(ch[i] * (1 - f) + next * f);
    }
    this.pos -= ch.length;
    if (this.out.length >= 4000) {
      const pcm = new Int16Array(this.out.length);
      for (let i = 0; i < pcm.length; i++) {
        pcm[i] = Math.max(-1, Math.min(1, this.out[i])) * 0x7fff;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
      this.out = [];
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PCMWorklet);
