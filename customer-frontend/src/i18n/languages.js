// The language registry. To add a language: create locales/<code>.js with the same keys as en.js, then add one entry
// here. Nothing else changes: the selector, the page text, the document language and the number and date formats
// all read from this list. `code` matches the voice backend's language codes, `locale` is the BCP 47 tag used for
// formatting and the page's lang attribute, and `dir` is "rtl" for a right-to-left language.
import en from "./locales/en.js";
import es from "./locales/es.js";
import pt from "./locales/pt.js";
import hi from "./locales/hi.js";

export const DEFAULT_LANGUAGE = "en";

// `label` is the language's own name, so a customer can find it whatever language the page is in.
export const LANGUAGES = [
  { code: "en", label: "English", locale: "en-US", dir: "ltr", messages: en },
  { code: "es", label: "Español", locale: "es-MX", dir: "ltr", messages: es },
  { code: "pt", label: "Português (Brasil)", locale: "pt-BR", dir: "ltr", messages: pt },
  { code: "hi", label: "हिन्दी", locale: "hi-IN", dir: "ltr", messages: hi },
];
