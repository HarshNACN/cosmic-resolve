import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_LANGUAGE, LANGUAGES } from "./languages.js";
import en from "./locales/en.js";
import { formatOrderDate, formatPrice, serverTextKey } from "../content.js";

// The one place the customer experience's language lives. The page text, the selector, the document language, the
// number and date formats and (when a voice call is attached) the voice session all follow it.
//
// The language changes in two ways, and both go through setLanguage:
//   - the customer picks one:        setLanguage(code)            -> source "manual": onManualChange(code) is told, so a
//                                                                    host can tell an active voice session
//   - the voice backend reports one: setLanguage(code, "voice")   -> never reported back, so the two cannot echo
// Setting the language it already has does nothing, which is the second guard against a loop: the backend's reply to a
// manual change is a `language` event for the same language, and that event changes nothing.
const LanguageContext = createContext(null);

function fill(template, params) {
  return template.replace(/\{(\w+)\}/g, (placeholder, name) => (params && name in params ? String(params[name]) : placeholder));
}

export function LanguageProvider({
  children,
  languages = LANGUAGES,
  supported = null, // codes the running voice system supports; null shows every registered language
  initial = DEFAULT_LANGUAGE,
  onManualChange,
}) {
  const [language, setCurrent] = useState(languages.some((entry) => entry.code === initial) ? initial : languages[0].code);
  const current = useRef(language);
  const manualCallback = useRef(onManualChange);
  manualCallback.current = onManualChange;

  const entry = languages.find((item) => item.code === language) ?? languages[0];

  // What the selector offers: the registered languages the voice system also supports. The current language always
  // stays in the list, and an empty or unknown list falls back to everything registered.
  const visible = useMemo(() => {
    if (!supported || supported.length === 0) return languages;
    const wanted = languages.filter((item) => supported.includes(item.code) || item.code === language);
    return wanted.length > 0 ? wanted : languages;
  }, [languages, supported, language]);

  const setLanguage = useCallback(
    (code, source = "manual") => {
      if (!languages.some((item) => item.code === code) || current.current === code) return;
      current.current = code;
      setCurrent(code);
      if (source === "manual") manualCallback.current?.(code);
    },
    [languages],
  );

  const onVoiceEvent = useCallback(
    (event) => {
      if (event && event.type === "language" && typeof event.language === "string") setLanguage(event.language, "voice");
    },
    [setLanguage],
  );

  useEffect(() => {
    const root = document.documentElement;
    const before = { lang: root.lang, dir: root.dir };
    root.lang = entry.locale;
    root.dir = entry.dir ?? "ltr";
    return () => {
      root.lang = before.lang;
      root.dir = before.dir;
    };
  }, [entry]);

  const value = useMemo(() => {
    const translate = (key, params) => fill(entry.messages[key] ?? en[key] ?? key, params);
    return {
      language,
      locale: entry.locale,
      dir: entry.dir ?? "ltr",
      languages: visible,
      setLanguage,
      onVoiceEvent,
      t: translate,
      // A customer-facing line for an API error: the localized text for its stable code, else the server's own words.
      errorText: (error) => (error?.code && en[`errors.${error.code}`] ? translate(`errors.${error.code}`) : (error?.message ?? "")),
      // Fixed server sentences are translated only on an exact match; anything else is shown as the server sent it.
      serverText: (text) => (serverTextKey(text) ? translate(serverTextKey(text)) : text),
      formatPrice: (amount) => formatPrice(amount, entry.locale),
      formatDate: (isoDate) => formatOrderDate(isoDate, entry.locale),
    };
  }, [entry, language, visible, setLanguage, onVoiceEvent]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("useLanguage must be used inside a LanguageProvider.");
  return value;
}
