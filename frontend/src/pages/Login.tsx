import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { LanguageSwitcher } from "../components/LanguageSwitcher";

interface DevTenantOption {
  user_id: string;
  tenant_id: string;
  tenant_name: string;
  email: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

// Dev-only tenant switcher (docs/ROADMAP.md) -- GET /auth/dev-tenants 404s
// unless the backend has ENVELOPS_DEV_AUTH_BYPASS_ENABLED set, so in any
// real deployment this silently fetches nothing and the dropdown below
// never renders. Never shown as an error to the user either way -- it's
// an optional convenience, not a feature whose absence is a problem.
function useDevTenants(): DevTenantOption[] {
  const [tenants, setTenants] = useState<DevTenantOption[]>([]);
  useEffect(() => {
    apiGet<DevTenantOption[]>("/auth/dev-tenants", null)
      .then(setTenants)
      .catch(() => setTenants([]));
  }, []);
  return tenants;
}

export default function Login() {
  const { t } = useTranslation();
  const { login, loginWithToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [devSwitching, setDevSwitching] = useState(false);

  const devTenants = useDevTenants();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch {
      // Same generic message the backend itself uses (app/auth/api.py) --
      // don't tell the caller whether the email or the password was wrong.
      setError(t("auth.invalidCredentials"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDevSwitch(userId: string) {
    if (!userId) return;
    setDevSwitching(true);
    try {
      const response = await apiPost<TokenResponse>(
        "/auth/dev-login",
        { user_id: userId },
        null,
      );
      loginWithToken(response.access_token);
    } finally {
      setDevSwitching(false);
    }
  }

  return (
    <section className="page login-page">
      <div className="login-page__corner">
        <LanguageSwitcher />
      </div>
      <div className="login-page__card">
        <h1>{t("auth.loginTitle")}</h1>
        <form className="form" onSubmit={(event) => void handleSubmit(event)}>
          <label className="form__field">
            {t("auth.email")}
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label className="form__field">
            {t("auth.password")}
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <button type="submit" className="button button--primary" disabled={submitting}>
            {submitting ? t("auth.loggingIn") : t("auth.login")}
          </button>
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
        </form>

        {devTenants.length > 0 && (
          <div className="login-page__dev-switch">
            <span className="dev-badge">{t("auth.devBadge")}</span>
            <label className="form__field">
              {t("auth.devTenantSwitch")}
              <select
                value=""
                disabled={devSwitching}
                onChange={(event) => void handleDevSwitch(event.target.value)}
              >
                <option value="" disabled>
                  {t("auth.devTenantSwitchPlaceholder")}
                </option>
                {devTenants.map((tenant) => (
                  <option key={tenant.user_id} value={tenant.user_id}>
                    {tenant.tenant_name} ({tenant.email})
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>
    </section>
  );
}
