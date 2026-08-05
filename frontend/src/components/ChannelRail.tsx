import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/useAuth";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useTheme } from "../context/theme/useTheme";
import { useMediaQuery, MOBILE_QUERY } from "../hooks/useMediaQuery";
import { CHANNEL_ICONS, CHANNEL_TYPES, isRealChannel } from "../lib/channels";
import {
  CheckIcon,
  ChatIcon,
  ChevronIcon,
  GlobeIcon,
  LogoutIcon,
  MoonIcon,
  MoreIcon,
  SunIcon,
} from "./icons";
import "./ChannelRail.css";

export function ChannelRail() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const { logout } = useAuth();
  const { isOpen, activeChannelType, openPanel, closePanel, pendingEscalationCountByChannelType } =
    useConversationPanel();
  const [menuOpen, setMenuOpen] = useState(false);
  const [langSubmenuOpen, setLangSubmenuOpen] = useState(false);
  const [themeSubmenuOpen, setThemeSubmenuOpen] = useState(false);
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname } = useLocation();

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

  // Same off-canvas-closes-on-navigate convention as Sidebar's own mobile
  // drawer -- a Sidebar nav click while this drawer happens to be open
  // shouldn't leave it open over whatever page that navigated to.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const isEnglish = i18n.resolvedLanguage !== "tr";
  const totalPendingEscalations = Object.values(pendingEscalationCountByChannelType).reduce(
    (sum, count) => sum + count,
    0,
  );

  // Mobile: collapses into a single trigger (badged with the total pending-
  // escalation count across every channel) that opens an off-canvas drawer
  // mirroring Sidebar's own mobile pattern -- same reasoning as that
  // component's mobile rework: a permanent 64px column has nowhere to go
  // on a phone-width viewport. The account menu (language/theme/logout)
  // renders as-is at the top of the drawer instead of being redesigned
  // into separate rows -- it's already a self-contained click-to-open
  // dropdown, so nesting it here needs no new logic.
  if (isMobile) {
    return (
      <>
        <button
          type="button"
          className="channel-rail__mobile-trigger"
          onClick={() => setMobileOpen(true)}
          aria-label={t("channelRail.openMenu")}
        >
          <ChatIcon className="channel-rail__mobile-trigger-icon" />
          {totalPendingEscalations > 0 && (
            <span className="channel-rail__badge">{totalPendingEscalations}</span>
          )}
        </button>
        {mobileOpen && <div className="sidebar-backdrop" onClick={() => setMobileOpen(false)} />}
        <nav
          className={`channel-rail--mobile${mobileOpen ? " channel-rail--mobile-open" : ""}`}
        >
          <div className="channel-rail__mobile-header">
            <strong>{t("channelRail.title")}</strong>
            <div className="channel-rail__mobile-header-actions">
              <div className="dropdown-menu channel-rail__mobile-account-menu">
                <button
                  type="button"
                  className="channel-rail__mobile-header-btn"
                  aria-expanded={menuOpen}
                  aria-label={t("channelRail.menu")}
                  title={t("channelRail.menu")}
                  onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
                >
                  <MoreIcon className="channel-rail__mobile-header-icon" />
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
              <button
                type="button"
                className="channel-rail__mobile-close"
                onClick={() => setMobileOpen(false)}
                aria-label={t("conversationPanel.close")}
              >
                ×
              </button>
            </div>
          </div>

          {CHANNEL_TYPES.map((key) => {
            const ChannelIcon = CHANNEL_ICONS[key];
            const real = isRealChannel(key);
            const isActive = isOpen && activeChannelType === key;
            const badgeCount = pendingEscalationCountByChannelType[key] ?? 0;
            const label = t(`channelRail.${key}`);
            return (
              <button
                key={key}
                type="button"
                className={`channel-rail__mobile-row${
                  isActive ? " channel-rail__mobile-row--active" : ""
                }`}
                onClick={() => {
                  // Never navigates (no route change to trigger the
                  // pathname effect above) -- explicit close needed here,
                  // same reasoning as Sidebar's own onClick items.
                  setMobileOpen(false);
                  if (isActive) {
                    closePanel();
                  } else {
                    openPanel(key);
                  }
                }}
              >
                <ChannelIcon
                  className={`channel-rail__mobile-row-icon${
                    real ? " channel-rail__mobile-row-icon--real" : ""
                  }`}
                />
                <span>{label}</span>
                {badgeCount > 0 && (
                  <span className="channel-rail__badge channel-rail__badge--inline">
                    {badgeCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </>
    );
  }

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

      {/* Every channel is clickable regardless of real vs. simulated --
          Test Console (frontend TestConsole.tsx) and the simulated
          webhooks (backend/app/channels/api.py) both let a conversation
          exist for any of them, so they open the panel showing that
          channel's conversations rather than rendering disabled. */}
      {CHANNEL_TYPES.map((key) => {
        const ChannelIcon = CHANNEL_ICONS[key];
        const real = isRealChannel(key);
        const isActive = isOpen && activeChannelType === key;
        const badgeCount = pendingEscalationCountByChannelType[key] ?? 0;
        const label = t(`channelRail.${key}`);
        const title = real
          ? `${label} — ${t("channelRail.realIntegration")}`
          : `${label} — ${t("channelRail.simulatedIntegration")}`;
        return (
          <button
            key={key}
            type="button"
            className={`channel-rail__icon${
              real ? " channel-rail__icon--real" : ""
            }${isActive ? " channel-rail__icon--active" : ""}`}
            title={title}
            aria-label={label}
            aria-pressed={isActive}
            onClick={() => (isActive ? closePanel() : openPanel(key))}
          >
            <ChannelIcon className="channel-rail__svg channel-rail__svg--channel" />
            {badgeCount > 0 && <span className="channel-rail__badge">{badgeCount}</span>}
          </button>
        );
      })}
    </nav>
  );
}
