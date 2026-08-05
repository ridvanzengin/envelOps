import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useMediaQuery, MOBILE_QUERY } from "../hooks/useMediaQuery";
import {
  ChannelsIcon,
  ChevronIcon,
  DashboardIcon,
  DocumentationIcon,
  FlaskIcon,
  GithubIcon,
  KnowledgeIcon,
  LogoMark,
  MenuIcon,
  PlugIcon,
  SettingsIcon,
} from "./icons";
import "./Sidebar.css";

interface NavItem {
  label: string;
  to: string;
  icon: typeof DashboardIcon;
  end?: boolean;
}

interface ExternalNavItem {
  label: string;
  href: string;
  icon: typeof DashboardIcon;
}

// Same key shape/prefix convention as the sibling reference project's own
// collapsed-sidebar persistence (iotops-workspace/IoTOps's Sidebar.tsx).
const COLLAPSED_STORAGE_KEY = "envelops:sidebar-collapsed";

function loadStoredCollapsed(): boolean {
  return typeof window !== "undefined" && window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
}

// Source Code leaves the app entirely -- a plain external link, not a
// route, same "Reference" grouping as the sibling reference project's
// own Sidebar (iotops-workspace/IoTOps).
const SOURCE_CODE_URL = "https://github.com/ridvanzengin/envelOps";
const ATTRIBUTION_URL = "https://ridvanzengin.github.io/";

export function Sidebar() {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(loadStoredCollapsed);
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname } = useLocation();
  const { closePanel } = useConversationPanel();

  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  // Closing on navigation matches every off-canvas mobile nav convention
  // (same as the sibling reference project's own mobile drawer,
  // iotops-workspace/IoTOps) -- otherwise the drawer stays open over the
  // new page until manually dismissed, which reads as stuck/broken.
  //
  // Also closes ConversationPanel on mobile specifically -- found live:
  // it's a full-screen overlay on mobile (ConversationPanel.css's
  // .conversation-panel--mobile), not a docked side panel like on
  // desktop, so leaving it open across a Sidebar navigation covered the
  // entire new page with no way back short of reopening the hamburger
  // menu. Desktop's docked panel intentionally keeps persisting across
  // navigation (it doesn't block anything there), so this is
  // mobile-only, not a general "always close on nav" change.
  useEffect(() => {
    setMobileOpen(false);
    if (isMobile) closePanel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function handleNavLinkClick() {
    if (isMobile) setMobileOpen(false);
  }

  // The desktop "collapsed" icon-rail shrink isn't a meaningful state once
  // inside the mobile drawer -- it's either fully open (full width, full
  // labels) or fully hidden, never a narrow icon-only rail on top of that.
  const effectiveCollapsed = isMobile ? false : collapsed;

  const navItems: NavItem[] = [
    { label: t("nav.dashboard"), to: "/", icon: DashboardIcon, end: true },
    { label: t("nav.channels"), to: "/channels", icon: ChannelsIcon },
    { label: t("nav.integrations"), to: "/integrations", icon: PlugIcon },
    { label: t("nav.knowledge"), to: "/knowledge", icon: KnowledgeIcon },
    { label: t("nav.testConsole"), to: "/test-console", icon: FlaskIcon },
    { label: t("nav.settings"), to: "/settings", icon: SettingsIcon },
  ];

  // Documentation is a real in-app route (renders inside the same app
  // shell), so it's a NavLink like the primary nav items above, just
  // grouped visually under "Reference".
  const referenceNavItems: NavItem[] = [
    { label: t("nav.documentation"), to: "/docs", icon: DocumentationIcon },
  ];

  const externalLinks: ExternalNavItem[] = [
    { label: t("nav.sourceCode"), href: SOURCE_CODE_URL, icon: GithubIcon },
  ];

  return (
    <>
      {isMobile && (
        <>
          {/* Standalone, not nested in .mobile-topbar below -- see its own
              CSS comment for why it has to be an independent fixed element
              to stay reachable above ConversationPanel's full-screen mobile
              overlay. */}
          <button
            type="button"
            className="mobile-topbar__menu-btn"
            onClick={() => setMobileOpen(true)}
            aria-label={t("sidebar.openMenu")}
          >
            <MenuIcon className="mobile-topbar__menu-icon" />
          </button>
          <div className="mobile-topbar">
            <NavLink to="/" end className="mobile-topbar__brand">
              <span className="sidebar__brand-mark">
                <LogoMark className="mobile-topbar__brand-icon" />
              </span>
              <span>EnvelOps</span>
            </NavLink>
          </div>
        </>
      )}
      {isMobile && mobileOpen && (
        <div className="sidebar-backdrop" onClick={() => setMobileOpen(false)} />
      )}
      <aside
        className={`sidebar${effectiveCollapsed ? " sidebar--collapsed" : ""}${
          isMobile ? ` sidebar--mobile${mobileOpen ? " sidebar--mobile-open" : ""}` : ""
        }`}
      >
        <div className="sidebar__header">
          <NavLink
            to="/"
            end
            className="sidebar__brand"
            title={effectiveCollapsed ? "EnvelOps" : undefined}
          >
            <span className="sidebar__brand-mark">
              <LogoMark className="sidebar__brand-icon" />
            </span>
            {!effectiveCollapsed && <span>EnvelOps</span>}
          </NavLink>
          <button
            type="button"
            className="sidebar__collapse-btn"
            onClick={() => (isMobile ? setMobileOpen(false) : setCollapsed((value) => !value))}
            title={isMobile ? t("sidebar.closeMenu") : collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            aria-label={isMobile ? t("sidebar.closeMenu") : collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            aria-expanded={isMobile ? undefined : !collapsed}
          >
            {isMobile ? "×" : <ChevronIcon className="sidebar__collapse-icon" />}
          </button>
        </div>
        <nav className="sidebar__nav">
          {navItems.map((item) => {
            const ItemIcon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `sidebar__link${isActive ? " sidebar__link--active" : ""}`
                }
                title={effectiveCollapsed ? item.label : undefined}
                onClick={handleNavLinkClick}
              >
                <ItemIcon className="sidebar__icon" />
                {!effectiveCollapsed && item.label}
              </NavLink>
            );
          })}

          {!effectiveCollapsed && <p className="sidebar__section-label">{t("sidebar.reference")}</p>}
          {referenceNavItems.map((item) => {
            const ItemIcon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `sidebar__link${isActive ? " sidebar__link--active" : ""}`
                }
                title={effectiveCollapsed ? item.label : undefined}
                onClick={handleNavLinkClick}
              >
                <ItemIcon className="sidebar__icon" />
                {!effectiveCollapsed && item.label}
              </NavLink>
            );
          })}
          {externalLinks.map((item) => {
            const ItemIcon = item.icon;
            return (
              <a
                key={item.label}
                href={item.href}
                target="_blank"
                rel="noopener noreferrer"
                className="sidebar__link"
                title={effectiveCollapsed ? item.label : undefined}
              >
                <ItemIcon className="sidebar__icon" />
                {!effectiveCollapsed && item.label}
              </a>
            );
          })}
        </nav>
        <div className="sidebar__footer">
          <a
            href={ATTRIBUTION_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar__attribution"
            title={effectiveCollapsed ? t("sidebar.attribution") : undefined}
          >
            {effectiveCollapsed ? "RZ" : t("sidebar.attribution")}
          </a>
        </div>
      </aside>
    </>
  );
}
