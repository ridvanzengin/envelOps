import type { ReactNode } from "react";

import { useDemoMode } from "../../hooks/useDemoMode";
import { DemoModeContext } from "./context";

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const enabled = useDemoMode();
  return <DemoModeContext.Provider value={{ enabled }}>{children}</DemoModeContext.Provider>;
}
