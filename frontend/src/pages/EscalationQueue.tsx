import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

interface Escalation {
  id: string;
  conversation_id: string;
  reason: string;
  layer: string;
  status: string;
  created_at: string;
}

export default function EscalationQueue() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();
  const [escalations, setEscalations] = useState<Escalation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await apiGet<Escalation[]>("/escalations", token);
      setEscalations(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(t("escalations.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleResolve(id: string) {
    setError(null);
    setResolvingId(id);
    try {
      const updated = await apiPost<Escalation>(
        `/escalations/${id}/resolve`,
        undefined,
        token,
      );
      setEscalations(
        (current) => current?.map((row) => (row.id === id ? updated : row)) ?? null,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(t("escalations.resolveError"));
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <section>
      <h1>{t("nav.escalations")}</h1>
      <p>{t("pages.escalations")}</p>
      {error && <p role="alert">{error}</p>}
      {escalations === null && !error && <p>{t("escalations.loading")}</p>}
      {escalations !== null && escalations.length === 0 && (
        <p>{t("escalations.empty")}</p>
      )}
      {escalations !== null && escalations.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>{t("escalations.reason")}</th>
              <th>{t("escalations.layer")}</th>
              <th>{t("escalations.status")}</th>
              <th>{t("escalations.createdAt")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {escalations.map((escalation) => (
              <tr key={escalation.id}>
                <td>{escalation.reason}</td>
                <td>{escalation.layer}</td>
                <td>{escalation.status}</td>
                <td>{new Date(escalation.created_at).toLocaleString()}</td>
                <td>
                  {escalation.status === "pending" && (
                    <button
                      type="button"
                      disabled={resolvingId === escalation.id}
                      onClick={() => void handleResolve(escalation.id)}
                    >
                      {resolvingId === escalation.id
                        ? t("escalations.resolving")
                        : t("escalations.resolve")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
