import { useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/useAuth";
import { LanguageSwitcher } from "../components/LanguageSwitcher";

export default function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
      </div>
    </section>
  );
}
