// Which languages the running voice system supports, so the selector offers exactly those. This reads one read-only
// metadata route of the voice backend (GET /api/voice/languages). It never loads a speech service, creates a session
// or touches a case. If the route is missing or unreachable (for example the voice backend is not running), it
// returns null and the page offers every language it has translations for: the page text works without the backend.
export async function fetchSupportedLanguageCodes(signal) {
  try {
    const response = await fetch("/api/voice/languages", { headers: { Accept: "application/json" }, signal });
    if (!response.ok) return null;
    const body = await response.json();
    const codes = Array.isArray(body?.languages) ? body.languages.map((item) => item?.code).filter((code) => typeof code === "string") : [];
    return codes.length > 0 ? codes : null;
  } catch {
    return null;
  }
}
