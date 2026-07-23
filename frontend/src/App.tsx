import { useTranslation } from "react-i18next";
import { NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import "./App.css";
import Dashboard from "./pages/Dashboard";
import EscalationQueue from "./pages/EscalationQueue";
import Inbox from "./pages/Inbox";
import KnowledgeSources from "./pages/KnowledgeSources";
import Settings from "./pages/Settings";

function LanguageSwitcher() {
  const { i18n } = useTranslation();
  return (
    <select
      value={i18n.resolvedLanguage}
      onChange={(e) => void i18n.changeLanguage(e.target.value)}
      aria-label="Language"
    >
      <option value="en">EN</option>
      <option value="tr">TR</option>
    </select>
  );
}

export default function App() {
  const { t } = useTranslation();
  return (
    <Router>
      <nav>
        <NavLink to="/">{t("nav.inbox")}</NavLink>
        <NavLink to="/escalations">{t("nav.escalations")}</NavLink>
        <NavLink to="/knowledge">{t("nav.knowledge")}</NavLink>
        <NavLink to="/settings">{t("nav.settings")}</NavLink>
        <NavLink to="/dashboard">{t("nav.dashboard")}</NavLink>
        <LanguageSwitcher />
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Inbox />} />
          <Route path="/escalations" element={<EscalationQueue />} />
          <Route path="/knowledge" element={<KnowledgeSources />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </main>
    </Router>
  );
}
