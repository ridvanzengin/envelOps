import { useTranslation } from "react-i18next";

import { GlobeIcon } from "./icons";

// A plain toggle button, not a dropdown -- only two languages are ever
// supported (i18n/index.ts's supportedLngs), so there's nothing a select
// buys over a single click. Login's own corner is the only consumer (the
// authenticated shell's language control lives in ChannelRail's own
// dropdown instead).
export function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const isEnglish = i18n.resolvedLanguage !== "tr";
  const nextLabel = isEnglish ? "Türkçeye geç" : "Switch to English";

  return (
    <button
      type="button"
      className="language-switcher"
      onClick={() => void i18n.changeLanguage(isEnglish ? "tr" : "en")}
      title={nextLabel}
      aria-label={nextLabel}
    >
      <GlobeIcon className="language-switcher__icon" />
      <span className="language-switcher__code">{isEnglish ? "EN" : "TR"}</span>
    </button>
  );
}
