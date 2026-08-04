import { createContext } from "react";

export interface DemoModeContextValue {
  // null while GET /system/demo-mode is still in flight -- every consumer
  // (Dashboard's tenant dropdown, the disabled-controls treatment on
  // Knowledge/Settings/Channels/escalation resolve) treats null the same
  // as false, since defaulting a button to enabled for one extra render
  // is harmless where defaulting App.tsx's own Login-vs-app-shell branch
  // the same way would flash the wrong screen -- see AppShell's own use
  // of this same value for why that one case waits instead.
  enabled: boolean | null;
}

export const DemoModeContext = createContext<DemoModeContextValue | null>(null);
