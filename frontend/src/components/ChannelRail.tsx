import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/useAuth";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useTheme } from "../context/theme/useTheme";
import {
  CheckIcon,
  ChevronIcon,
  EmailIcon,
  FacebookIcon,
  GlobeIcon,
  InstagramIcon,
  LogoutIcon,
  MoonIcon,
  MoreIcon,
  SunIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "./icons";
import "./ChannelRail.css";

// Only Telegram is a real, built channel (app/channels/ backend) -- the
// rest have no real integration yet, but are still clickable: Test Console
// (frontend TestConsole.tsx) lets a test conversation exist for any of
// them, so they open the panel showing that channel's (always test-only)
// conversations rather than rendering disabled.
const CHANNELS = [
  { key: "telegram", icon: TelegramIcon, real: true },
  { key: "whatsapp", icon: WhatsAppIcon, real: false },
  { key: "facebook", icon: FacebookIcon, real: false },
  { key: "instagram", icon: InstagramIcon, real: false },
  { key: "email", icon: EmailIcon, real: false },
] as const;

export function ChannelRail() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const { logout } = useAuth();
  const { isOpen, activeChannelType, openPanel, closePanel, pendingEscalationCountByChannelType } =
    useConversationPanel();
  const [menuOpen, setMenuOpen] = useState(false);
  const [langSubmenuOpen, setLangSubmenuOpen] = useState(false);
  const [themeSubmenuOpen, setThemeSubmenuOpen] = useState(false);

  function closeMenu() {
    setMenuOpen(false);
    setLangSubmenuOpen(false);
    setThemeSubmenuOpen(false);
  }

  // Same click-outside convention as every other .dropdown-menu consumer
  // in the sibling reference project -- a mousedown anywhere outside the
  // menu's own DOM subtree closes it.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!(event.target instanceof Element) || !event.target.closest(".dropdown-menu")) {
        closeMenu();
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
          onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
        >
          <MoreIcon className="channel-rail__svg" />
        </button>
        {menuOpen && (
          <div className="dropdown-menu__list">
            <button
              type="button"
              className="dropdown-menu__item dropdown-menu__item--parent"
              aria-expanded={langSubmenuOpen}
              onClick={() => setLangSubmenuOpen((value) => !value)}
            >
              <GlobeIcon className="dropdown-menu__item-icon" />
              {t("menu.language")}
              <ChevronIcon
                className={`chevron dropdown-menu__item-chevron${
                  langSubmenuOpen ? " chevron--expanded" : ""
                }`}
              />
            </button>
            {langSubmenuOpen && (
              <div className="dropdown-menu__submenu">
                <button
                  type="button"
                  className="dropdown-menu__item dropdown-menu__item--sub"
                  onClick={() => {
                    closeMenu();
                    void i18n.changeLanguage("en");
                  }}
                >
                  English
                  {isEnglish && <CheckIcon className="dropdown-menu__item-icon" />}
                </button>
                <button
                  type="button"
                  className="dropdown-menu__item dropdown-menu__item--sub"
                  onClick={() => {
                    closeMenu();
                    void i18n.changeLanguage("tr");
                  }}
                >
                  Türkçe
                  {!isEnglish && <CheckIcon className="dropdown-menu__item-icon" />}
                </button>
              </div>
            )}

            <button
              type="button"
              className="dropdown-menu__item dropdown-menu__item--parent"
              aria-expanded={themeSubmenuOpen}
              onClick={() => setThemeSubmenuOpen((value) => !value)}
            >
              {theme === "dark" ? (
                <MoonIcon className="dropdown-menu__item-icon" />
              ) : (
                <SunIcon className="dropdown-menu__item-icon" />
              )}
              {t("menu.theme")}
              <ChevronIcon
                className={`chevron dropdown-menu__item-chevron${
                  themeSubmenuOpen ? " chevron--expanded" : ""
                }`}
              />
            </button>
            {themeSubmenuOpen && (
              <div className="dropdown-menu__submenu">
                <button
                  type="button"
                  className="dropdown-menu__item dropdown-menu__item--sub"
                  onClick={() => {
                    closeMenu();
                    setTheme("light");
                  }}
                >
                  {t("theme.light")}
                  {theme === "light" && <CheckIcon className="dropdown-menu__item-icon" />}
                </button>
                <button
                  type="button"
                  className="dropdown-menu__item dropdown-menu__item--sub"
                  onClick={() => {
                    closeMenu();
                    setTheme("dark");
                  }}
                >
                  {t("theme.dark")}
                  {theme === "dark" && <CheckIcon className="dropdown-menu__item-icon" />}
                </button>
              </div>
            )}

            <button
              type="button"
              className="dropdown-menu__item dropdown-menu__item--danger"
              onClick={() => {
                closeMenu();
                logout();
              }}
            >
              <LogoutIcon className="dropdown-menu__item-icon" />
              {t("auth.logout")}
            </button>
          </div>
        )}
      </div>

      <div className="channel-rail__divider" />

      {CHANNELS.map(({ key, icon: ChannelIcon, real }) => {
        const isActive = isOpen && activeChannelType === key;
        const badgeCount = pendingEscalationCountByChannelType[key] ?? 0;
        const label = t(`channelRail.${key}`);
        const title = real ? label : `${label} — ${t("channelRail.testOnly")}`;
        return (
          <button
            key={key}
            type="button"
            className={`channel-rail__icon${
              real ? " channel-rail__icon--telegram" : ""
            }${isActive ? " channel-rail__icon--active" : ""}`}
            title={title}
            aria-label={label}
            aria-pressed={isActive}
            onClick={() => (isActive ? closePanel() : openPanel(key))}
          >
            <ChannelIcon className="channel-rail__svg" />
            {badgeCount > 0 && <span className="channel-rail__badge">{badgeCount}</span>}
          </button>
        );
      })}
    </nav>
  );
}
