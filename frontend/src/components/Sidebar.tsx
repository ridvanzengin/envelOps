import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useTheme } from "../context/theme/useTheme";
import {
  DashboardIcon,
  KnowledgeIcon,
  LogoMark,
  LogoutIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
} from "./icons";
import "./Sidebar.css";

interface NavItem {
  label: string;
  to: string;
  icon: typeof DashboardIcon;
  end?: boolean;
}

export function Sidebar({ onLogout }: { onLogout: () => void }) {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();

  const navItems: NavItem[] = [
    { label: t("nav.dashboard"), to: "/", icon: DashboardIcon, end: true },
    { label: t("nav.knowledge"), to: "/knowledge", icon: KnowledgeIcon },
    { label: t("nav.settings"), to: "/settings", icon: SettingsIcon },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <span className="sidebar__brand">
          <span className="sidebar__brand-mark">
            <LogoMark className="sidebar__brand-icon" />
          </span>
          <span>EnvelOps</span>
        </span>
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
            >
              <ItemIcon className="sidebar__icon" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__link sidebar__link--button"
          onClick={toggleTheme}
          aria-label={t("theme.toggle")}
          title={t("theme.toggle")}
        >
          {theme === "dark" ? (
            <SunIcon className="sidebar__icon" />
          ) : (
            <MoonIcon className="sidebar__icon" />
          )}
          {t("theme.toggle")}
        </button>
        <button
          type="button"
          className="sidebar__link sidebar__link--button"
          onClick={onLogout}
        >
          <LogoutIcon className="sidebar__icon" />
          {t("auth.logout")}
        </button>
      </div>
    </aside>
  );
}
