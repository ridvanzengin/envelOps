import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  ChannelsIcon,
  ChevronIcon,
  DashboardIcon,
  FlaskIcon,
  KnowledgeIcon,
  LogoMark,
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

// Same key shape/prefix convention as the sibling reference project's own
// collapsed-sidebar persistence (iotops-workspace/IoTOps's Sidebar.tsx).
const COLLAPSED_STORAGE_KEY = "envelops:sidebar-collapsed";

function loadStoredCollapsed(): boolean {
  return typeof window !== "undefined" && window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
}

export function Sidebar() {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(loadStoredCollapsed);

  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  const navItems: NavItem[] = [
    { label: t("nav.dashboard"), to: "/", icon: DashboardIcon, end: true },
    { label: t("nav.channels"), to: "/channels", icon: ChannelsIcon },
    { label: t("nav.integrations"), to: "/integrations", icon: PlugIcon },
    { label: t("nav.knowledge"), to: "/knowledge", icon: KnowledgeIcon },
    { label: t("nav.testConsole"), to: "/test-console", icon: FlaskIcon },
    { label: t("nav.settings"), to: "/settings", icon: SettingsIcon },
  ];

  return (
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`}>
      <div className="sidebar__header">
        <NavLink to="/" end className="sidebar__brand" title={collapsed ? "EnvelOps" : undefined}>
          <span className="sidebar__brand-mark">
            <LogoMark className="sidebar__brand-icon" />
          </span>
          {!collapsed && <span>EnvelOps</span>}
        </NavLink>
        <button
          type="button"
          className="sidebar__collapse-btn"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
          aria-label={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
          aria-expanded={!collapsed}
        >
          <ChevronIcon className="sidebar__collapse-icon" />
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
              title={collapsed ? item.label : undefined}
            >
              <ItemIcon className="sidebar__icon" />
              {!collapsed && item.label}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
