// Plays raw 16-bit mono PCM as it streams in, one chunk after another with no gaps, and reports the output level
// so the headset animation can follow the voice. The AudioContext is created inside unlock(), which must be called
// from a user gesture (the click that starts the call) or the browser will keep it silent.

function toFloat32(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const samples = new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2));
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) out[i] = samples[i] / 32768;
  return out;
}

export class PcmPlayer {
  constructor({ onPlayingChange, onLevel } = {}) {
    this.onPlayingChange = onPlayingChange || (() => {});
    this.onLevel = onLevel || (() => {});
    this.context = null;
    this.analyser = null;
    this.nextStart = 0;
    this.active = new Set();
    this.idleWaiters = [];
    this.frame = null;
    this.playing = false;
  }

  async unlock() {
    if (!this.context) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return false;
      this.context = new Context();
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.connect(this.context.destination);
    }
    if (this.context.state === "suspended") await this.context.resume();
    return true;
  }

  enqueue(base64Pcm, rate) {
    if (!this.context) return;
    const samples = toFloat32(base64Pcm);
    if (samples.length === 0) return;
    const buffer = this.context.createBuffer(1, samples.length, rate);
    buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser);
    const startAt = Math.max(this.context.currentTime + 0.02, this.nextStart);
    source.start(startAt);
    this.nextStart = startAt + buffer.duration;
    this.active.add(source);
    source.onended = () => {
      this.active.delete(source);
      if (this.active.size === 0) this.#becomeIdle();
    };
    this.#setPlaying(true);
  }

  // Stop at once (the customer interrupted, or the call ended).
  stop() {
    for (const source of this.active) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already stopped
      }
    }
    this.active.clear();
    this.nextStart = 0;
    this.#becomeIdle();
  }

  // Resolves when everything queued so far has finished playing.
  whenIdle() {
    return this.playing ? new Promise((resolve) => this.idleWaiters.push(resolve)) : Promise.resolve();
  }

  close() {
    this.stop();
    this.context?.close?.();
    this.context = null;
  }

  #becomeIdle() {
    this.#setPlaying(false);
    const waiters = this.idleWaiters.splice(0);
    waiters.forEach((resolve) => resolve());
  }

  #setPlaying(playing) {
    if (this.playing === playing) return;
    this.playing = playing;
    this.onPlayingChange(playing);
    if (playing) this.#measure();
    else {
      if (this.frame !== null) cancelAnimationFrame(this.frame);
      this.frame = null;
      this.onLevel(0);
    }
  }

  #measure() {
    const data = new Uint8Array(this.analyser.fftSize);
    const tick = () => {
      this.analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 1) {
        const centered = (data[i] - 128) / 128;
        sum += centered * centered;
      }
      this.onLevel(Math.min(1, Math.sqrt(sum / data.length) * 3));
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }
}
