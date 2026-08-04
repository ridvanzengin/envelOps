import { useContext } from "react";

import { DemoModeContext } from "./context";
import type { DemoModeContextValue } from "./context";

export function useDemoModeContext(): DemoModeContextValue {
  const context = useContext(DemoModeContext);
  if (context === null) {
    throw new Error("useDemoModeContext must be used within a DemoModeProvider");
  }
  return context;
}
