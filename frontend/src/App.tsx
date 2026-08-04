import { useEffect } from "react";
import { Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";

import "./App.css";
import { apiPost } from "./api/client";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./auth/useAuth";
import { ChannelRail } from "./components/ChannelRail";
import { ConversationPanel } from "./components/ConversationPanel";
import { Sidebar } from "./components/Sidebar";
import { ConversationPanelProvider } from "./context/conversationPanel/ConversationPanelContext";
import { DemoModeProvider } from "./context/demoMode/DemoModeProvider";
import { useDemoModeContext } from "./context/demoMode/useDemoModeContext";
import { ThemeProvider } from "./context/theme/ThemeContext";
import { useDevTenants } from "./hooks/useDevTenants";
import Channels from "./pages/Channels";
import Dashboard from "./pages/Dashboard";
import Integrations from "./pages/Integrations";
import KnowledgeSources from "./pages/KnowledgeSources";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import TestConsole from "./pages/TestConsole";

interface DevLoginResponse {
  access_token: string;
  token_type: string;
}

function BootLoading() {
  const { t } = useTranslation();
  return (
    <section className="page login-page">
      <div className="login-page__card">
        <p>{t("app.loading")}</p>
      </div>
    </section>
  );
}

function AppShell() {
  const { token, loginWithToken } = useAuth();
  const { enabled: demoModeEnabled } = useDemoModeContext();
  const devTenants = useDevTenants();

  // Demo mode never shows a real login screen -- auto-logs in as the
  // first showcase tenant the instant the dev-tenants list loads. Tenant
  // switching from there on is Dashboard.tsx's own tenant dropdown (demo
  // mode only), not this effect again -- it only ever fires while token
  // is still null.
  useEffect(() => {
    if (demoModeEnabled && token === null && devTenants.length > 0) {
      void apiPost<DevLoginResponse>(
        "/auth/dev-login",
        { user_id: devTenants[0].user_id },
        null,
      ).then((response) => loginWithToken(response.access_token));
    }
  }, [demoModeEnabled, token, devTenants, loginWithToken]);

  // Single "owner" role, Phase 1 (docs/ARCHITECTURE.md §2) -- one gate for
  // the whole app is enough; there's no per-route permission distinction
  // to model yet. Login owns its own corner language switcher (no shared
  // top bar above the shell) since a Turkish-speaking owner needs it to
  // read the login screen too, not just the app after logging in (§7).
  if (demoModeEnabled === null || (token === null && demoModeEnabled)) {
    // Either GET /system/demo-mode hasn't resolved yet, or it has and
    // demo mode's own auto-login above is in flight -- both are brief,
    // both mean "not ready to decide between Login and the app shell yet".
    return <BootLoading />;
  }

  if (token === null) {
    return <Login />;
  }

  return (
    <ConversationPanelProvider>
      <Router>
        <div className="app-shell">
          <Sidebar />
          <div className="app-content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/channels" element={<Channels />} />
              <Route path="/integrations" element={<Integrations />} />
              <Route path="/knowledge" element={<KnowledgeSources />} />
              <Route path="/test-console" element={<TestConsole />} />
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
      <DemoModeProvider>
        <AuthProvider>
          <AppShell />
        </AuthProvider>
      </DemoModeProvider>
    </ThemeProvider>
  );
}
