import { useTranslation } from "react-i18next";

import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { EmailIcon, FacebookIcon, InstagramIcon, TelegramIcon, WhatsAppIcon } from "./icons";
import "./ChannelRail.css";

// Only Telegram is a real, built channel (app/channels/ backend) -- the
// rest render disabled/"coming soon", same convention as a locked nav item,
// not fake working icons. No channel_id filtering: every real conversation
// today is already Telegram, so the Telegram icon just opens the existing
// full conversation list.
const DISABLED_CHANNELS = [
  { key: "whatsapp", icon: WhatsAppIcon },
  { key: "facebook", icon: FacebookIcon },
  { key: "instagram", icon: InstagramIcon },
  { key: "email", icon: EmailIcon },
] as const;

export function ChannelRail() {
  const { t } = useTranslation();
  const { isOpen, openPanel, closePanel, pendingEscalationCount } = useConversationPanel();

  return (
    <nav className="channel-rail">
      <button
        type="button"
        className={`channel-rail__icon channel-rail__icon--telegram${
          isOpen ? " channel-rail__icon--active" : ""
        }`}
        title={t("channelRail.telegram")}
        aria-label={t("channelRail.telegram")}
        aria-pressed={isOpen}
        onClick={() => (isOpen ? closePanel() : openPanel())}
      >
        <TelegramIcon className="channel-rail__svg" />
        {pendingEscalationCount > 0 && (
          <span className="channel-rail__badge">{pendingEscalationCount}</span>
        )}
      </button>
      {DISABLED_CHANNELS.map(({ key, icon: ChannelIcon }) => (
        <span
          key={key}
          className="channel-rail__icon channel-rail__icon--disabled"
          title={`${t(`channelRail.${key}`)} — ${t("channelRail.comingSoon")}`}
        >
          <ChannelIcon className="channel-rail__svg" />
        </span>
      ))}
    </nav>
  );
}
