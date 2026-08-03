import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  EmailIcon,
  FacebookIcon,
  InstagramIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "../components/icons";
import { CHANNEL_TYPES, isRealChannel } from "../lib/channels";
import type { ChannelType } from "../lib/channels";
import "./Channels.css";

// Same per-channel icon map ChannelRail.tsx/Settings.tsx/TestConsole.tsx
// each already keep their own copy of -- not centralized in lib/channels.ts
// (that file's own comment says icons stay a rendering concern, not
// coupled into the shared type list), so a fourth small copy here
// follows the existing precedent rather than diverging from it.
const CHANNEL_ICONS: Record<ChannelType, typeof TelegramIcon> = {
  telegram: TelegramIcon,
  whatsapp: WhatsAppIcon,
  facebook: FacebookIcon,
  instagram: InstagramIcon,
  email: EmailIcon,
};

export default function Channels() {
  const { t } = useTranslation();

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.channels")}</h1>
        <div className="channels__toolbar">
          <button
            type="button"
            className="button"
            disabled
            title={t("channels.comingSoon")}
          >
            {t("channels.testAllChannels")}
          </button>
          <button
            type="button"
            className="button"
            disabled
            title={t("channels.comingSoon")}
          >
            {t("channels.addChannel")}
          </button>
        </div>
      </div>
      <p className="page__description">{t("pages.channels")}</p>

      <div className="card">
        <ul className="channels__list">
          {CHANNEL_TYPES.map((type) => {
            const Icon = CHANNEL_ICONS[type];
            const real = isRealChannel(type);
            return (
              <li key={type} className="channels__row">
                <span className="channels__row-icon">
                  <Icon />
                </span>
                <span className="channels__row-name">{t(`channelRail.${type}`)}</span>
                <span
                  className={`channels__badge${real ? " channels__badge--real" : ""}`}
                >
                  {real
                    ? t("channelRail.realIntegration")
                    : t("channelRail.simulatedIntegration")}
                </span>
                <span className="channels__row-status">{t("channels.autoReplyAlwaysOn")}</span>
                <button
                  type="button"
                  className="button"
                  disabled
                  title={t("channels.comingSoon")}
                >
                  {t("channels.configure")}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="channels__settings-link">
        {t("channels.settingsLinkText")}{" "}
        <Link to="/settings">{t("channels.settingsLinkLabel")}</Link>
      </p>
    </section>
  );
}
