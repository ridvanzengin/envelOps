import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/useAuth";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useTheme } from "../context/theme/useTheme";
import {
  EmailIcon,
  FacebookIcon,
  InstagramIcon,
  LogoutIcon,
  MoonIcon,
  SunIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "./icons";
import { LanguageSwitcher } from "./LanguageSwitcher";
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
  const { theme, toggleTheme } = useTheme();
  const { logout } = useAuth();
  const { isOpen, openPanel, closePanel, pendingEscalationCount } = useConversationPanel();

  return (
    <nav className="channel-rail">
      <LanguageSwitcher showLabel={false} className="channel-rail__icon" />
      <button
        type="button"
        className="channel-rail__icon"
        onClick={toggleTheme}
        title={t("theme.toggle")}
        aria-label={t("theme.toggle")}
      >
        {theme === "dark" ? (
          <SunIcon className="channel-rail__svg" />
        ) : (
          <MoonIcon className="channel-rail__svg" />
        )}
      </button>
      <button
        type="button"
        className="channel-rail__icon"
        onClick={logout}
        title={t("auth.logout")}
        aria-label={t("auth.logout")}
      >
        <LogoutIcon className="channel-rail__svg" />
      </button>

      <div className="channel-rail__divider" />

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
