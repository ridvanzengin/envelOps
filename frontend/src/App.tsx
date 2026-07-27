import { useTranslation } from "react-i18next";
import { NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import "./App.css";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./auth/useAuth";
import Dashboard from "./pages/Dashboard";
import EscalationQueue from "./pages/EscalationQueue";
import Inbox from "./pages/Inbox";
import KnowledgeSources from "./pages/KnowledgeSources";
import Login from "./pages/Login";
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

function AppShell() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();

  // Single "owner" role, Phase 1 (docs/ARCHITECTURE.md §2) -- one gate for
  // the whole app is enough; there's no per-route permission distinction
  // to model yet. The language switcher itself lives one level up
  // (outside this gate, see App()) since a Turkish-speaking owner needs
  // it to read the login screen too, not just the app after logging in
  // (§7: Turkish + English are both Phase 1, not just for the pipeline).
  if (token === null) {
    return <Login />;
  }

  return (
    <Router>
      <nav>
        <NavLink to="/">{t("nav.inbox")}</NavLink>
        <NavLink to="/escalations">{t("nav.escalations")}</NavLink>
        <NavLink to="/knowledge">{t("nav.knowledge")}</NavLink>
        <NavLink to="/settings">{t("nav.settings")}</NavLink>
        <NavLink to="/dashboard">{t("nav.dashboard")}</NavLink>
        <button type="button" onClick={logout}>
          {t("auth.logout")}
        </button>
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

export default function App() {
  return (
    <AuthProvider>
      <div className="app-language-bar">
        <LanguageSwitcher />
      </div>
      <AppShell />
    </AuthProvider>
  );
}
