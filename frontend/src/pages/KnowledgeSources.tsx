import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiDelete, apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { TrashIcon } from "../components/icons";

interface KnowledgeSource {
  id: string;
  type: string;
  source_uri: string | null;
  last_synced_at: string | null;
  chunk_count: number;
}

type SourceType = "manual" | "url";

export default function KnowledgeSources() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();
  const [sources, setSources] = useState<KnowledgeSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [type, setType] = useState<SourceType>("manual");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await apiGet<KnowledgeSource[]>("/knowledge/sources", token);
      setSources(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(t("knowledgeSources.loadError"));
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
      const body = type === "manual" ? { type, content } : { type, url };
      const created = await apiPost<KnowledgeSource>("/knowledge/sources", body, token);
      setSources((current) => (current ? [created, ...current] : [created]));
      setContent("");
      setUrl("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      // The backend's own 400 detail (e.g. "url is required when type is
      // 'url'", "no text content found to ingest") is meant to be shown
      // to the caller, not a security-sensitive detail to hide -- unlike
      // login's generic-on-purpose message.
      setFormError(err instanceof ApiError ? err.message : t("knowledgeSources.addError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRefresh(id: string) {
    setError(null);
    setRefreshingId(id);
    try {
      const updated = await apiPost<KnowledgeSource>(
        `/knowledge/sources/${id}/refresh`,
        undefined,
        token,
      );
      setSources(
        (current) => current?.map((row) => (row.id === id ? updated : row)) ?? null,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : t("knowledgeSources.refreshError"));
    } finally {
      setRefreshingId(null);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm(t("knowledgeSources.deleteConfirm"))) return;
    setError(null);
    setDeletingId(id);
    try {
      await apiDelete(`/knowledge/sources/${id}`, token);
      setSources((current) => current?.filter((row) => row.id !== id) ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : t("knowledgeSources.deleteError"));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.knowledge")}</h1>
      </div>
      <p className="page__description">{t("pages.knowledge")}</p>

      <form className="form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="form__field">
          {t("knowledgeSources.type")}
          <select value={type} onChange={(e) => setType(e.target.value as SourceType)}>
            <option value="manual">{t("knowledgeSources.typeManual")}</option>
            <option value="url">{t("knowledgeSources.typeUrl")}</option>
          </select>
        </label>
        {type === "manual" ? (
          <label className="form__field">
            {t("knowledgeSources.content")}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
            />
          </label>
        ) : (
          <label className="form__field">
            {t("knowledgeSources.url")}
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} required />
          </label>
        )}
        <button type="submit" className="button button--primary" disabled={submitting}>
          {submitting ? t("knowledgeSources.adding") : t("knowledgeSources.add")}
        </button>
        {formError && (
          <p className="error-message" role="alert">
            {formError}
          </p>
        )}
      </form>

      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {sources === null && !error && <p>{t("knowledgeSources.loading")}</p>}
      {sources !== null && sources.length === 0 && (
        <div className="empty-state">{t("knowledgeSources.empty")}</div>
      )}
      {sources !== null && sources.length > 0 && (
        <div className="card">
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("knowledgeSources.sourceType")}</th>
                  <th>{t("knowledgeSources.sourceUri")}</th>
                  <th>{t("knowledgeSources.chunkCount")}</th>
                  <th>{t("knowledgeSources.lastSynced")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.id}>
                    <td>{source.type}</td>
                    <td>{source.source_uri ?? "—"}</td>
                    <td>{source.chunk_count}</td>
                    <td>
                      {source.last_synced_at
                        ? new Date(source.last_synced_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="table__actions">
                      {source.type === "url" && (
                        <button
                          type="button"
                          className="button button--primary"
                          disabled={refreshingId === source.id}
                          onClick={() => void handleRefresh(source.id)}
                        >
                          {refreshingId === source.id
                            ? t("knowledgeSources.refreshing")
                            : t("knowledgeSources.refresh")}
                        </button>
                      )}
                      <button
                        type="button"
                        className="button button--danger"
                        disabled={deletingId === source.id}
                        onClick={() => void handleDelete(source.id)}
                        aria-label={t("knowledgeSources.delete")}
                        title={t("knowledgeSources.delete")}
                      >
                        <TrashIcon />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
