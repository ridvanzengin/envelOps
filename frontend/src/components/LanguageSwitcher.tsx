import { useTranslation } from "react-i18next";

import { GlobeIcon } from "./icons";

// A plain toggle button, not a dropdown -- only two languages are ever
// supported (i18n/index.ts's supportedLngs), so there's nothing a select
// buys over a single click. showLabel=false renders icon-only, matching
// ChannelRail's other icon-button controls; the default (label shown)
// is for Login's own corner, which has room for the "EN"/"TR" text.
export function LanguageSwitcher({
  showLabel = true,
  className,
}: {
  showLabel?: boolean;
  className?: string;
}) {
  const { i18n } = useTranslation();
  const isEnglish = i18n.resolvedLanguage !== "tr";
  const nextLabel = isEnglish ? "Türkçeye geç" : "Switch to English";

  return (
    <button
      type="button"
      className={className ?? "language-switcher"}
      onClick={() => void i18n.changeLanguage(isEnglish ? "tr" : "en")}
      title={nextLabel}
      aria-label={nextLabel}
    >
      <GlobeIcon className={showLabel ? "language-switcher__icon" : "channel-rail__svg"} />
      {showLabel && <span className="language-switcher__code">{isEnglish ? "EN" : "TR"}</span>}
    </button>
  );
}
