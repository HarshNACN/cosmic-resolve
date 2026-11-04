// Client for the local voice endpoints (/api/voice/*). All voice code lives in src/voice so it stays separate from
// the case workbench. A turn is a streamed response of newline-delimited JSON events:
//   customer_text, stage, agent_sentence, audio, case_created, state, error, done
// and, with multilingual calls on: language, agent_text (shown, not spoken), voice_unavailable

const BASE = "/api/voice";

export class VoiceApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "VoiceApiError";
    this.status = status;
  }
}

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

function detailOf(body) {
  if (isObject(body) && typeof body.detail === "string") return body.detail;
  if (isObject(body) && Array.isArray(body.detail) && typeof body.detail[0]?.msg === "string") return body.detail[0].msg;
  return null;
}

async function failure(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return new VoiceApiError(detailOf(body) || `The voice service returned an error (${response.status}).`, response.status);
}

async function send(path, init) {
  try {
    return await fetch(`${BASE}${path}`, init);
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new VoiceApiError("Cannot reach the voice service.");
  }
}

async function json(path, init) {
  const response = await send(path, { ...init, headers: { Accept: "application/json", ...(init?.headers || {}) } });
  if (!response.ok) throw await failure(response);
  const body = await response.json().catch(() => null);
  if (!isObject(body)) throw new VoiceApiError("The voice service returned an unexpected response.");
  return body;
}

// Reads a streamed response line by line, calling onEvent for each parsed event as soon as it arrives.
// A partial line is held until its newline shows up, so chunk boundaries never split an event.
export async function readEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  const flush = (line) => {
    const text = line.trim();
    if (!text) return;
    let event = null;
    try {
      event = JSON.parse(text);
    } catch {
      return; // ignore a malformed line rather than ending the call
    }
    if (isObject(event) && typeof event.type === "string") onEvent(event);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    const lines = pending.split("\n");
    pending = lines.pop() ?? "";
    lines.forEach(flush);
  }
  flush(pending + decoder.decode());
}

async function stream(path, init, onEvent) {
  const response = await send(path, init);
  if (!response.ok) throw await failure(response);
  await readEvents(response, onEvent);
}

export const voiceWarmup = (signal) => json("/warmup", { method: "POST", signal });

export const fetchCallers = (signal) => json("/callers", { signal });

export const createVoiceSession = (customerId, signal, language) =>
  json("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(language ? { customer_id: customerId, language } : { customer_id: customerId }),
    signal,
  });

// The manual language selector. Streams the re-asked step in the new language (en, es or pt).
export const setCallLanguage = (sessionId, language, onEvent, signal) =>
  stream(
    `/sessions/${encodeURIComponent(sessionId)}/language`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language }), signal },
    onEvent,
  );

export const fetchVoiceSession = (sessionId, signal) => json(`/sessions/${encodeURIComponent(sessionId)}`, { signal });

// kind is "greeting" or "outcome".
export const speakLine = (sessionId, kind, onEvent, signal) =>
  stream(
    `/sessions/${encodeURIComponent(sessionId)}/speak`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind }), signal },
    onEvent,
  );

// Exactly one of audio (a Blob), text, or orderId.
export function sendTurn(sessionId, { audio, text, orderId }, onEvent, signal) {
  const form = new FormData();
  if (audio) form.append("audio", audio, "speech.webm");
  else if (orderId) form.append("order_id", orderId);
  else form.append("text", text ?? "");
  return stream(`/sessions/${encodeURIComponent(sessionId)}/turn`, { method: "POST", body: form, signal }, onEvent);
}
