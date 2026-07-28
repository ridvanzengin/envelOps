import { useTranslation } from "react-i18next";
import { Route, BrowserRouter as Router, Routes } from "react-router-dom";

import "./App.css";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./auth/useAuth";
import { ChannelRail } from "./components/ChannelRail";
import { ConversationPanel } from "./components/ConversationPanel";
import { GlobeIcon } from "./components/icons";
import { Sidebar } from "./components/Sidebar";
import { ConversationPanelProvider } from "./context/conversationPanel/ConversationPanelContext";
import { ThemeProvider } from "./context/theme/ThemeContext";
import Dashboard from "./pages/Dashboard";
import KnowledgeSources from "./pages/KnowledgeSources";
import Login from "./pages/Login";
import Settings from "./pages/Settings";

function LanguageSwitcher() {
  const { i18n } = useTranslation();
  return (
    <label className="language-switcher">
      <GlobeIcon className="language-switcher__icon" />
      <select
        value={i18n.resolvedLanguage}
        onChange={(e) => void i18n.changeLanguage(e.target.value)}
        aria-label="Language"
      >
        <option value="en">EN</option>
        <option value="tr">TR</option>
      </select>
    </label>
  );
}

function AppShell() {
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
    <ConversationPanelProvider>
      <Router>
        <div className="app-shell">
          <Sidebar onLogout={logout} />
          <div className="app-content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/knowledge" element={<KnowledgeSources />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
          <ConversationPanel />
          <ChannelRail />
        </div>
      </Router>
    </ConversationPanelProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <div className="app-topbar">
          <LanguageSwitcher />
        </div>
        <AppShell />
      </AuthProvider>
    </ThemeProvider>
  );
}
