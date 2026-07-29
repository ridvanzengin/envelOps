import { Route, BrowserRouter as Router, Routes } from "react-router-dom";

import "./App.css";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./auth/useAuth";
import { ChannelRail } from "./components/ChannelRail";
import { ConversationPanel } from "./components/ConversationPanel";
import { Sidebar } from "./components/Sidebar";
import { ConversationPanelProvider } from "./context/conversationPanel/ConversationPanelContext";
import { ThemeProvider } from "./context/theme/ThemeContext";
import Dashboard from "./pages/Dashboard";
import KnowledgeSources from "./pages/KnowledgeSources";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import TestConsole from "./pages/TestConsole";

function AppShell() {
  const { token } = useAuth();

  // Single "owner" role, Phase 1 (docs/ARCHITECTURE.md §2) -- one gate for
  // the whole app is enough; there's no per-route permission distinction
  // to model yet. Login owns its own corner language switcher (no shared
  // top bar above the shell) since a Turkish-speaking owner needs it to
  // read the login screen too, not just the app after logging in (§7).
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
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </ThemeProvider>
  );
}
