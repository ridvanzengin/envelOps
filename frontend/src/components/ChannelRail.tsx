import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/useAuth";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useTheme } from "../context/theme/useTheme";
import {
  EmailIcon,
  FacebookIcon,
  InstagramIcon,
  MoreIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "./icons";
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
  const { t, i18n } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { logout } = useAuth();
  const { isOpen, openPanel, closePanel, pendingEscalationCount } = useConversationPanel();
  const [menuOpen, setMenuOpen] = useState(false);

  // Same click-outside convention as every other .dropdown-menu consumer
  // in the sibling reference project -- a mousedown anywhere outside the
  // menu's own DOM subtree closes it.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!(event.target instanceof Element) || !event.target.closest(".dropdown-menu")) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const isEnglish = i18n.resolvedLanguage !== "tr";

  return (
    <nav className="channel-rail">
      <div className="dropdown-menu">
        <button
          type="button"
          className="channel-rail__icon"
          aria-label={t("channelRail.menu")}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((value) => !value)}
        >
          <MoreIcon className="channel-rail__svg" />
        </button>
        {menuOpen && (
          <div className="dropdown-menu__list">
            <button
              type="button"
              className="dropdown-menu__item"
              onClick={() => {
                setMenuOpen(false);
                void i18n.changeLanguage(isEnglish ? "tr" : "en");
              }}
            >
              {isEnglish ? "Türkçe" : "English"}
            </button>
            <button
              type="button"
              className="dropdown-menu__item"
              onClick={() => {
                setMenuOpen(false);
                toggleTheme();
              }}
            >
              {theme === "dark" ? t("theme.switchToLight") : t("theme.switchToDark")}
            </button>
            <button
              type="button"
              className="dropdown-menu__item dropdown-menu__item--danger"
              onClick={() => {
                setMenuOpen(false);
                logout();
              }}
            >
              {t("auth.logout")}
            </button>
          </div>
        )}
      </div>

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
