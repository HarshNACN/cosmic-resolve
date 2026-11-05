import { useCallback, useEffect, useRef, useState } from "react";

const MAX_RECORDING_MS = 25000;
const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

function pickMimeType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return PREFERRED_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

// Tap-to-talk recording. start() asks for the microphone (the browser shows its permission prompt the first time),
// stop() resolves with the recorded Blob. A recording is capped so a forgotten tap cannot run on forever.
export function useRecorder({ onAutoStop } = {}) {
  const [recording, setRecording] = useState(false);
  const recorder = useRef(null);
  const stream = useRef(null);
  const chunks = useRef([]);
  const timer = useRef(null);
  const resolveStop = useRef(null);
  const autoStop = useRef(onAutoStop);
  autoStop.current = onAutoStop;

  const release = useCallback(() => {
    clearTimeout(timer.current);
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    recorder.current = null;
    setRecording(false);
  }, []);

  const start = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw Object.assign(new Error("This browser cannot record audio. Use the typing box instead."), { code: "NO_RECORDER" });
    }
    let media;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      throw Object.assign(new Error("Microphone access was blocked. Allow the microphone for this site, or use the typing box."), {
        code: "MIC_BLOCKED",
      });
    }
    stream.current = media;
    chunks.current = [];
    const mimeType = pickMimeType();
    const next = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
    next.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.current.push(event.data);
    };
    next.onstop = () => {
      const blob = new Blob(chunks.current, { type: next.mimeType || mimeType || "audio/webm" });
      release();
      resolveStop.current?.(blob);
      resolveStop.current = null;
    };
    recorder.current = next;
    next.start();
    setRecording(true);
    timer.current = setTimeout(() => autoStop.current?.(), MAX_RECORDING_MS);
  }, [release]);

  const stop = useCallback(
    () =>
      new Promise((resolve) => {
        if (!recorder.current || recorder.current.state === "inactive") {
          resolve(null);
          return;
        }
        resolveStop.current = resolve;
        recorder.current.stop();
      }),
    [],
  );

  const cancel = useCallback(() => {
    if (recorder.current && recorder.current.state !== "inactive") {
      recorder.current.onstop = null;
      recorder.current.stop();
    }
    resolveStop.current = null;
    release();
  }, [release]);

  useEffect(() => cancel, [cancel]);

  return { recording, start, stop, cancel };
}
