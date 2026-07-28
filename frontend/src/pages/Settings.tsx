import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

interface TriggerPhrase {
  id: string;
  phrase: string;
}

// System defaults (docs/ARCHITECTURE.md §5) are compiled regex in
// app/escalation/safety_gate.py, not DB rows -- there's nothing to fetch
// for them, so these three category labels are static, translated copy
// mirroring safety_gate.py's own three checks. Shown locked: no edit, no
// delete, ever, by design.
const SYSTEM_DEFAULT_CATEGORY_KEYS = [
  "contraindication",
  "symptom",
  "outcomeGuarantee",
] as const;

export default function Settings() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();
  const [phrases, setPhrases] = useState<TriggerPhrase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newPhrase, setNewPhrase] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await apiGet<TriggerPhrase[]>(
        "/escalations/trigger-phrases",
        token,
      );
      setPhrases(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(t("settings.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const created = await apiPost<TriggerPhrase>(
        "/escalations/trigger-phrases",
        { phrase: newPhrase },
        token,
      );
      setPhrases((current) => (current ? [...current, created] : [created]));
      setNewPhrase("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setFormError(err instanceof ApiError ? err.message : t("settings.addError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page">
      <h1>{t("nav.settings")}</h1>
      <p>{t("pages.settings")}</p>

      <h2>{t("settings.safetyTriggersTitle")}</h2>

      <h3>{t("settings.systemDefaultsTitle")}</h3>
      <ul>
        {SYSTEM_DEFAULT_CATEGORY_KEYS.map((key) => (
          <li key={key}>
            <label>
              <input type="checkbox" checked disabled />
              {t(`settings.systemDefaultCategories.${key}`)}
            </label>
          </li>
        ))}
      </ul>

      <h3>{t("settings.tenantPhrasesTitle")}</h3>
      {error && <p role="alert">{error}</p>}
      {phrases === null && !error && <p>{t("settings.loading")}</p>}
      {phrases !== null && phrases.length === 0 && <p>{t("settings.empty")}</p>}
      {phrases !== null && phrases.length > 0 && (
        <ul>
          {phrases.map((phrase) => (
            <li key={phrase.id}>{phrase.phrase}</li>
          ))}
        </ul>
      )}

      <form onSubmit={(event) => void handleSubmit(event)}>
        <label>
          {t("settings.newPhrase")}
          <input
            type="text"
            value={newPhrase}
            onChange={(e) => setNewPhrase(e.target.value)}
            required
          />
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? t("settings.adding") : t("settings.add")}
        </button>
        {formError && <p role="alert">{formError}</p>}
      </form>
    </section>
  );
}
