import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import tr from "./locales/tr.json";

// This is the dashboard's own language switch (docs/ARCHITECTURE.md §7) —
// unrelated to what language the pipeline detects in a customer's DM.
//
// detection.order deliberately excludes "navigator" (the device/browser's
// own OS locale) -- LanguageDetector's default order includes it, which
// meant a first-time visitor whose phone is set to Turkish saw a Turkish
// UI even though fallbackLng is "en". fallbackLng only applies when
// detection finds nothing at all; it doesn't apply when detection
// successfully finds a *supported* language via navigator, which Turkish
// is. Restricting detection to "localStorage" means: nothing stored yet
// -> detection finds nothing -> fallbackLng "en" wins, but a user who
// explicitly picks Turkish via the language switcher still gets it
// remembered (LanguageDetector caches changeLanguage() calls into
// localStorage by default) and reloaded on their next visit.
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      tr: { translation: tr },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "tr"],
    detection: {
      order: ["localStorage"],
      caches: ["localStorage"],
    },
    interpolation: { escapeValue: false },
  });

export default i18n;
