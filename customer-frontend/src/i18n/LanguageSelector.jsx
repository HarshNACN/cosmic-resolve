import { useLanguage } from "./LanguageProvider.jsx";

// The visible language selector. It lists the languages the running voice system supports, each by its own name, and
// it stays in the header through every step. Changing it never touches the form: only the language state changes.
export default function LanguageSelector() {
  const { language, languages, setLanguage, t } = useLanguage();
  return (
    <div className="language-selector">
      <label htmlFor="language-select" className="visually-hidden">
        {t("language.label")}
      </label>
      <select id="language-select" value={language} onChange={(event) => setLanguage(event.target.value)}>
        {languages.map((item) => (
          <option key={item.code} value={item.code} lang={item.locale}>
            {item.label}
          </option>
        ))}
      </select>
    </div>
  );
}
