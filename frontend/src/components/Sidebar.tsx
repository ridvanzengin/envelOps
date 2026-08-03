import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  ChannelsIcon,
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

export function Sidebar() {
  const { t } = useTranslation();

  const navItems: NavItem[] = [
    { label: t("nav.dashboard"), to: "/", icon: DashboardIcon, end: true },
    { label: t("nav.channels"), to: "/channels", icon: ChannelsIcon },
    { label: t("nav.integrations"), to: "/integrations", icon: PlugIcon },
    { label: t("nav.knowledge"), to: "/knowledge", icon: KnowledgeIcon },
    { label: t("nav.testConsole"), to: "/test-console", icon: FlaskIcon },
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
    </aside>
  );
}
