import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import HeadsetAvatar, { PHASE_LABELS } from "../voice/HeadsetAvatar.jsx";
import { PcmPlayer } from "../voice/pcmPlayer.js";
import { VoiceApiError, readEvents, sendTurn } from "../voice/voiceApi.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

const encoder = new TextEncoder();
function responseOf(chunks) {
  return {
    body: new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
        controller.close();
      },
    }),
  };
}

describe("reading streamed events", () => {
  it("delivers each event as soon as its line is complete, even when a chunk splits a line", async () => {
    const seen = [];
    await readEvents(responseOf(['{"type":"a","n":1}\n{"type":"b"', ',"n":2}\n', '{"type":"c"}']), (e) => seen.push(e));
    expect(seen).toEqual([{ type: "a", n: 1 }, { type: "b", n: 2 }, { type: "c" }]);
  });

  it("skips malformed lines and objects without a type instead of ending the call", async () => {
    const seen = [];
    await readEvents(responseOf(['not json\n{"no":"type"}\n[1,2]\n{"type":"ok"}\n']), (e) => seen.push(e));
    expect(seen).toEqual([{ type: "ok" }]);
  });

  it("decodes a multi-byte character that arrives split across chunks", async () => {
    const bytes = encoder.encode('{"type":"t","text":"café"}\n');
    const cut = bytes.indexOf(0xc3) + 1; // between the two bytes of the e-acute
    const seen = [];
    await readEvents(
      { body: new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, cut)); c.enqueue(bytes.slice(cut)); c.close(); } }) },
      (e) => seen.push(e),
    );
    expect(seen[0].text).toBe("café");
  });
});

describe("sending a turn", () => {
  // A response, or a function making a fresh one for each call (a stream can only be read once).
  function stubFetch(response) {
    const fetchMock = vi.fn(async () => (typeof response === "function" ? response() : response));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("sends audio, a tapped order, or typed text as a form, never more than one", async () => {
    const fetchMock = stubFetch(() => ({ ok: true, ...responseOf([]) }));
    await sendTurn("s1", { audio: new Blob(["x"]) }, () => {});
    await sendTurn("s1", { orderId: "O-1" }, () => {});
    await sendTurn("s1", { text: "hello" }, () => {});
    const bodies = fetchMock.mock.calls.map(([, init]) => init.body);
    expect([...bodies[0].keys()]).toEqual(["audio"]);
    expect([...bodies[1].keys()]).toEqual(["order_id"]);
    expect([...bodies[2].keys()]).toEqual(["text"]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/voice/sessions/s1/turn");
  });

  it("turns a refused request into a readable error", async () => {
    stubFetch({ ok: false, status: 413, json: async () => ({ detail: "That recording is too long." }) });
    await expect(sendTurn("s1", { text: "x" }, () => {})).rejects.toMatchObject({
      name: "VoiceApiError",
      message: "That recording is too long.",
      status: 413,
    });
  });

  it("explains an unreachable service plainly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(sendTurn("s1", { text: "x" }, () => {})).rejects.toBeInstanceOf(VoiceApiError);
  });

  it("lets an aborted request surface as an abort, not an error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); }));
    await expect(sendTurn("s1", { text: "x" }, () => {})).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("the headset illustration", () => {
  it.each(Object.keys(PHASE_LABELS))("names the %s state in words, not only in motion", (phase) => {
    render(<HeadsetAvatar phase={phase} />);
    const image = screen.getByRole("img");
    expect(image).toHaveAttribute("data-state", phase);
    expect(image).toHaveAccessibleName(`Cosmo, the voice assistant. ${PHASE_LABELS[phase]}.`);
  });

  it("passes the speaking level to the animation and falls back safely for an unknown phase", () => {
    const { rerender } = render(<HeadsetAvatar phase="speaking" level={0.456} />);
    expect(screen.getByRole("img").style.getPropertyValue("--level")).toBe("0.46");
    rerender(<HeadsetAvatar phase="nonsense" />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/Ready to start a call/);
  });
});

describe("the audio player", () => {
  function fakeAudio() {
    const sources = [];
    class FakeContext {
      constructor() {
        this.state = "suspended";
        this.currentTime = 10;
        this.destination = {};
      }
      createAnalyser() {
        return { fftSize: 0, connect: vi.fn(), getByteTimeDomainData: (data) => data.fill(128) };
      }
      createBuffer(channels, length, rate) {
        return { duration: length / rate, length, rate, copyToChannel: vi.fn() };
      }
      createBufferSource() {
        const source = { connect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null };
        sources.push(source);
        return source;
      }
      async resume() {
        this.state = "running";
      }
      close() {}
    }
    vi.stubGlobal("AudioContext", FakeContext);
    vi.stubGlobal("requestAnimationFrame", (cb) => setTimeout(cb, 5));
    vi.stubGlobal("cancelAnimationFrame", (id) => clearTimeout(id));
    return sources;
  }
  // 4 samples of 16-bit PCM ("AAAAAAAA" is 6 bytes of silence; use 8 bytes for 4 samples).
  const PCM = btoa(String.fromCharCode(...new Uint8Array(8)));

  it("stays silent until it has been unlocked, then schedules chunks back to back", async () => {
    const sources = fakeAudio();
    const playing = [];
    const player = new PcmPlayer({ onPlayingChange: (p) => playing.push(p) });
    player.enqueue(PCM, 22050);
    expect(sources).toHaveLength(0);

    await player.unlock();
    player.enqueue(PCM, 22050);
    player.enqueue(PCM, 22050);
    const [first, second] = sources;
    expect(second.start.mock.calls[0][0]).toBeCloseTo(first.start.mock.calls[0][0] + 4 / 22050, 6);
    expect(playing).toEqual([true]);
  });

  it("goes idle when the last chunk ends and resolves anyone waiting for that", async () => {
    const sources = fakeAudio();
    const playing = [];
    const player = new PcmPlayer({ onPlayingChange: (p) => playing.push(p) });
    await player.unlock();
    player.enqueue(PCM, 22050);
    let idle = false;
    const waiting = player.whenIdle().then(() => {
      idle = true;
    });
    expect(idle).toBe(false);
    sources[0].onended();
    await waiting;
    expect(idle).toBe(true);
    expect(playing).toEqual([true, false]);
  });

  it("stops everything at once when the customer interrupts", async () => {
    const sources = fakeAudio();
    const levels = [];
    const player = new PcmPlayer({ onLevel: (l) => levels.push(l) });
    await player.unlock();
    player.enqueue(PCM, 22050);
    player.enqueue(PCM, 22050);
    player.stop();
    expect(sources.every((s) => s.stop.mock.calls.length === 1)).toBe(true);
    await expect(player.whenIdle()).resolves.toBeUndefined();
    expect(levels.at(-1)).toBe(0);
  });

  it("copes with a browser that has no audio support", async () => {
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", undefined);
    const player = new PcmPlayer();
    expect(await player.unlock()).toBe(false);
    expect(() => player.enqueue(PCM, 22050)).not.toThrow();
  });
});
