import { useState } from "react";
import type { ReactNode } from "react";

import { ThemeContext } from "./context";
import type { Theme } from "./context";

const STORAGE_KEY = "envelops-theme";

// index.html sets documentElement's data-theme attribute before first
// paint (localStorage, defaulting to dark) so there's no flash of the
// wrong theme -- this just reads whatever it already landed on as React's
// own initial state, so this provider and the CSS never disagree.
function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(currentTheme);

  function setTheme(next: Theme) {
    document.documentElement.dataset.theme = next;
    localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  }

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
  );
}
