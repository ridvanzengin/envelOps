import { useContext } from "react";

import { ThemeContext } from "./context";
import type { ThemeContextValue } from "./context";

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
