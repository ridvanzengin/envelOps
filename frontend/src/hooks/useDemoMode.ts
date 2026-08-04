import { useEffect, useState } from "react";

import { apiGet } from "../api/client";

interface DemoModeStatus {
  enabled: boolean;
}

// null while the initial GET /system/demo-mode is in flight -- App.tsx
// must not decide whether to show Login until this resolves, or a real
// deployment would flash Login and a demo deployment would flash it the
// other way. Unauthenticated on purpose (main.py's own endpoint docstring)
// -- this has to resolve before App.tsx even knows whether a login screen
// makes sense at all.
export function useDemoMode(): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    apiGet<DemoModeStatus>("/system/demo-mode", null)
      .then((result) => setEnabled(result.enabled))
      .catch(() => setEnabled(false));
  }, []);
  return enabled;
}
