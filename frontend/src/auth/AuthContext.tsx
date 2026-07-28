import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { apiPost } from "../api/client";
import { AuthContext } from "./context";

const TOKEN_STORAGE_KEY = "envelops.token";

interface LoginResponse {
  access_token: string;
  token_type: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_STORAGE_KEY),
  );

  const loginWithToken = useCallback((accessToken: string) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
    setToken(accessToken);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await apiPost<LoginResponse>(
        "/auth/login",
        { email, password },
        null,
      );
      loginWithToken(response.access_token);
    },
    [loginWithToken],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
  }, []);

  const value = useMemo(
    () => ({ token, login, loginWithToken, logout }),
    [token, login, loginWithToken, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
