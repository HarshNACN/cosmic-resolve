import { useCallback, useEffect, useRef, useState } from "react";
import { PcmPlayer } from "./pcmPlayer.js";
import { useRecorder } from "./useRecorder.js";
import {
  VoiceApiError,
  createVoiceSession,
  fetchVoiceSession,
  sendTurn,
  setCallLanguage,
  speakLine,
  voiceWarmup,
} from "./voiceApi.js";

const POLL_MS = 1500;
const MIN_RECORDING_BYTES = 1200; // anything smaller is a stray tap, not speech
const TALKABLE = new Set(["listening", "speaking", "waiting"]);

const DEFAULT_LOCALES = { en: "en-US", es: "es-MX", pt: "pt-BR", hi: "hi-IN" };

// The browser's own voice, used only when the server has no voice for the line. The locale picks the right accent.
function speakInBrowser(text, language, capabilities) {
  if (!text || !("speechSynthesis" in window)) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = capabilities?.browser_locales?.[language] || DEFAULT_LOCALES[language] || DEFAULT_LOCALES.en;
  window.speechSynthesis.speak(utterance);
}

// The text to show for an error. With a translator (tr) the errors that have a stable code are translated; without
// one it is the error's own message. customerSafe hides server-written setup detail from a customer: any server-side
// failure becomes one plain "voice isn't working" sentence, and a rejected session says the session ended.
function messageOf(error, tr, customerSafe) {
  if (!(error instanceof Error)) return tr("voice.errors.GENERIC", "Something went wrong. Please try again.");
  if (customerSafe && error instanceof VoiceApiError) {
    if (error.status === 401) return tr("voice.errors.SESSION", error.message);
    if (error.status !== null && error.status >= 500) return tr("voice.errors.UNAVAILABLE", error.message);
  }
  return error.code ? tr(`voice.errors.${error.code}`, error.message) : error.message;
}

// Phases: idle, connecting, speaking, listening, recording, thinking, waiting (for the specialist), resolved, ended.
// onLanguageChange(language, source) is told about every `language` event the backend sends (source is "speech", "text",
// "request" or "manual"), so a host page can keep its own language in step with the call. It is optional.
// t(key, fallback, params) translates the hook's own messages and getAuthHeaders() supplies the Authorization header for
// the request that opens a call (both optional; see CallPanel).
export function useVoiceCall({ onCaseCreated, onLanguageChange, t, getAuthHeaders } = {}) {
  const tr = t ?? ((key, fallback) => fallback);
  const trRef = useRef(tr);
  trRef.current = tr;
  const authHeaders = useRef(getAuthHeaders);
  authHeaders.current = getAuthHeaders;
  const [phase, setPhase] = useState("idle");
  const [session, setSession] = useState(null);
  // What the notice is about, not its text: { error }, { key, fallback } or { text } (the server's own words). It is turned
  // into text on every render, so a notice already showing follows a language change.
  const [noticeSource, setNotice] = useState(null);
  const [level, setLevel] = useState(0);
  const [capabilities, setCapabilities] = useState(null);
  const [missingVoice, setMissingVoice] = useState(null); // label of a language whose voice is not installed

  const player = useRef(null);
  const abort = useRef(null);
  const sessionRef = useRef(null);
  const capabilitiesRef = useRef(null);
  const phaseRef = useRef("idle");
  const languageChoice = useRef(undefined); // set before a call starts; sent when the session is created
  const finishRecordingRef = useRef(() => {});
  const caseCallback = useRef(onCaseCreated);
  caseCallback.current = onCaseCreated;
  const languageCallback = useRef(onLanguageChange);
  languageCallback.current = onLanguageChange;

  const recorder = useRecorder({ onAutoStop: () => finishRecordingRef.current() });

  // The first warm-up loads the voice and opens the model connection, which can take many seconds on a cold start.
  // Do it as soon as the page opens so nobody waits for it when they press Start call.
  const warmUp = useRef(null);
  const prepare = useCallback(() => {
    if (!warmUp.current) {
      warmUp.current = voiceWarmup().then((status) => {
        capabilitiesRef.current = status;
        setCapabilities(status);
        return status;
      });
      warmUp.current.catch(() => {
        warmUp.current = null; // a failed warm-up is retried when the call starts
      });
    }
    return warmUp.current;
  }, []);
  useEffect(() => {
    prepare().catch(() => {});
  }, [prepare]);

  const go = useCallback((next) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const keepSession = useCallback((next) => {
    sessionRef.current = next;
    setSession(next);
  }, []);

  // Where the call goes after the agent has finished talking.
  const settle = useCallback(() => {
    const state = sessionRef.current?.state;
    if (state === "SUBMITTED") go("waiting");
    else if (state === "CLOSED") go(sessionRef.current?.outcome ? "resolved" : "ended");
    else go("listening");
  }, [go]);

  const handleEvent = useCallback(
    (event) => {
      switch (event.type) {
        case "customer_text":
          keepSession({
            ...sessionRef.current,
            transcript: [...(sessionRef.current?.transcript || []), { role: "customer", text: event.text }],
          });
          break;
        case "stage":
          go("thinking");
          break;
        case "agent_sentence":
          keepSession({
            ...sessionRef.current,
            transcript: [...(sessionRef.current?.transcript || []), { role: "agent", text: event.text }],
          });
          // No server voice (Piper not set up): read the line with the browser's own voice instead.
          if (capabilitiesRef.current && !capabilitiesRef.current.tts) {
            speakInBrowser(event.text, event.lang || sessionRef.current?.language, capabilitiesRef.current);
          }
          go("speaking");
          break;
        case "agent_text":
          // The associate's approved message in its original wording: shown, never spoken or translated.
          keepSession({
            ...sessionRef.current,
            transcript: [...(sessionRef.current?.transcript || []), { role: "agent", text: event.text, note: true }],
          });
          break;
        case "language":
          keepSession({ ...sessionRef.current, language: event.language });
          setMissingVoice(null);
          languageCallback.current?.(event.language, event.source);
          break;
        case "voice_unavailable":
          // Text still works. Say so, and read the line with the browser's voice for that locale if there is one.
          setMissingVoice(event.label || event.language);
          speakInBrowser(sessionRef.current?.transcript?.at(-1)?.text || "", event.language, capabilitiesRef.current);
          go("speaking");
          break;
        case "audio":
          player.current?.enqueue(event.pcm, event.rate);
          go("speaking");
          break;
        case "case_created":
          caseCallback.current?.(event.case_id);
          break;
        case "state":
          keepSession(event.session);
          break;
        case "error":
          setNotice({ text: event.message });
          break;
        default:
          break;
      }
    },
    [go, keepSession],
  );

  // Runs one streamed exchange, then waits for the speech to finish before deciding what happens next.
  const run = useCallback(
    async (start) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setNotice(null);
      try {
        await start(handleEvent, controller.signal);
        await player.current?.whenIdle();
      } catch (error) {
        if (error && error.name === "AbortError") return;
        setNotice({ error });
      }
      if (!controller.signal.aborted) settle();
    },
    [handleEvent, settle],
  );

  const startCall = useCallback(
    async (customerId) => {
      setNotice(null);
      go("connecting");
      player.current = player.current || new PcmPlayer({ onLevel: setLevel });
      await player.current.unlock(); // inside the click that started the call, so the browser allows sound
      try {
        await prepare();
        const snapshot = await createVoiceSession(customerId, undefined, languageChoice.current, authHeaders.current?.());
        keepSession(snapshot);
        await run((onEvent, signal) => speakLine(snapshot.session_id, "greeting", onEvent, signal));
      } catch (error) {
        setNotice({ error });
        go("idle");
      }
    },
    [go, keepSession, prepare, run],
  );

  const interrupt = useCallback(() => {
    abort.current?.abort(); // the customer cut in: stop the stream and the audio together
    player.current?.stop();
    window.speechSynthesis?.cancel?.();
  }, []);

  const finishRecording = useCallback(async () => {
    const blob = await recorder.stop();
    if (!blob || blob.size < MIN_RECORDING_BYTES) {
      setNotice({ key: "voice.errors.TOO_SHORT", fallback: "That was too short to hear. Tap the microphone and speak again." });
      settle();
      return;
    }
    go("thinking");
    run((onEvent, signal) => sendTurn(sessionRef.current.session_id, { audio: blob }, onEvent, signal));
  }, [go, recorder, run, settle]);
  finishRecordingRef.current = finishRecording;

  const toggleMic = useCallback(async () => {
    if (phaseRef.current === "recording") {
      await finishRecording();
      return;
    }
    if (!sessionRef.current || !TALKABLE.has(phaseRef.current)) return;
    if (phaseRef.current === "speaking") interrupt();
    try {
      await recorder.start();
      go("recording");
    } catch (error) {
      setNotice({ error });
      settle();
    }
  }, [finishRecording, go, interrupt, recorder, settle]);

  const talk = useCallback(
    (input) => {
      if (!sessionRef.current || !TALKABLE.has(phaseRef.current)) return;
      if (phaseRef.current === "speaking") interrupt();
      go("thinking");
      run((onEvent, signal) => sendTurn(sessionRef.current.session_id, input, onEvent, signal));
    },
    [go, interrupt, run],
  );

  // The manual selector. Re-asks the current step in the new language; never starts a case or ends the call.
  const changeLanguage = useCallback(
    (language) => {
      languageChoice.current = language;
      if (!sessionRef.current) return;
      if (!TALKABLE.has(phaseRef.current)) return;
      if (phaseRef.current === "speaking") interrupt();
      go("thinking");
      run((onEvent, signal) => setCallLanguage(sessionRef.current.session_id, language, onEvent, signal));
    },
    [go, interrupt, run],
  );

  const sendText = useCallback((text) => talk({ text }), [talk]);
  const chooseOrder = useCallback((orderId) => talk({ orderId }), [talk]);

  const endCall = useCallback(() => {
    interrupt();
    recorder.cancel();
    go("ended");
  }, [go, interrupt, recorder]);

  const resetCall = useCallback(() => {
    interrupt();
    recorder.cancel();
    keepSession(null);
    setNotice(null);
    setMissingVoice(null);
    go("idle");
  }, [go, interrupt, keepSession, recorder]);

  // While a specialist is reviewing, ask now and then whether they have decided, then say the outcome out loud.
  useEffect(() => {
    if (phase !== "waiting" || !sessionRef.current) return undefined;
    const sessionId = sessionRef.current.session_id;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const snapshot = await fetchVoiceSession(sessionId);
        if (cancelled || !snapshot.outcome) return;
        clearInterval(timer);
        keepSession(snapshot);
        run((onEvent, signal) => speakLine(sessionId, "outcome", onEvent, signal));
      } catch {
        // a missed poll is not an error; try again next tick
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [phase, keepSession, run]);

  useEffect(
    () => () => {
      abort.current?.abort();
      player.current?.close();
      window.speechSynthesis?.cancel?.();
    },
    [],
  );

  const customerSafe = Boolean(getAuthHeaders);
  const notice = !noticeSource
    ? null
    : noticeSource.error
      ? messageOf(noticeSource.error, tr, customerSafe)
      : noticeSource.key
        ? tr(noticeSource.key, noticeSource.fallback)
        : noticeSource.text;

  return {
    phase,
    session,
    notice,
    level,
    capabilities,
    missingVoice,
    changeLanguage,
    recording: recorder.recording,
    startCall,
    toggleMic,
    sendText,
    chooseOrder,
    endCall,
    resetCall,
    dismissNotice: () => setNotice(null),
  };
}
