import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiDelete, apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { TrashIcon } from "../components/icons";

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
  const [deletingId, setDeletingId] = useState<string | null>(null);

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

  async function handleDelete(id: string) {
    if (!window.confirm(t("settings.deleteConfirm"))) return;
    setError(null);
    setDeletingId(id);
    try {
      await apiDelete(`/escalations/trigger-phrases/${id}`, token);
      setPhrases((current) => current?.filter((row) => row.id !== id) ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : t("settings.deleteError"));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.settings")}</h1>
      </div>
      <p className="page__description">{t("pages.settings")}</p>

      <h2>{t("settings.safetyTriggersTitle")}</h2>

      <h3>{t("settings.systemDefaultsTitle")}</h3>
      <div className="card">
        <ul className="list">
          {SYSTEM_DEFAULT_CATEGORY_KEYS.map((key) => (
            <li key={key} className="list__item">
              <label>
                <input type="checkbox" checked disabled />
                {t(`settings.systemDefaultCategories.${key}`)}
              </label>
            </li>
          ))}
        </ul>
      </div>

      <h3>{t("settings.tenantPhrasesTitle")}</h3>
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {phrases === null && !error && <p>{t("settings.loading")}</p>}
      {phrases !== null && phrases.length === 0 && (
        <div className="empty-state">{t("settings.empty")}</div>
      )}
      {phrases !== null && phrases.length > 0 && (
        <div className="card">
          <ul className="list">
            {phrases.map((phrase) => (
              <li key={phrase.id} className="list__item list__item--with-action">
                <span>{phrase.phrase}</span>
                <button
                  type="button"
                  className="button button--danger"
                  disabled={deletingId === phrase.id}
                  onClick={() => void handleDelete(phrase.id)}
                  aria-label={t("settings.delete")}
                  title={t("settings.delete")}
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="form__field">
          {t("settings.newPhrase")}
          <input
            type="text"
            value={newPhrase}
            onChange={(e) => setNewPhrase(e.target.value)}
            required
          />
        </label>
        <button type="submit" className="button button--primary" disabled={submitting}>
          {submitting ? t("settings.adding") : t("settings.add")}
        </button>
        {formError && (
          <p className="error-message" role="alert">
            {formError}
          </p>
        )}
      </form>
    </section>
  );
}
