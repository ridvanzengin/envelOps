import { createContext } from "react";

export interface AuthContextValue {
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  // Stores an already-issued token directly, skipping the email/password
  // call login() makes -- used by the dev-only tenant switcher
  // (docs/ROADMAP.md), which gets its token from POST /auth/dev-login
  // instead.
  loginWithToken: (token: string) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
