import { useCallback, useEffect, useState } from "react";
import type { ComponentType, FormEvent, SVGProps } from "react";
import { useTranslation } from "react-i18next";

import { apiDelete, apiGet, apiPost, apiPostFile, apiPut, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useDemoModeContext } from "../context/demoMode/useDemoModeContext";
import {
  ChevronIcon,
  CheckIcon,
  CopyIcon,
  DatabaseIcon,
  FileTextIcon,
  GlobeIcon,
  ClockIcon,
  LayersIcon,
  MoreIcon,
  PencilIcon,
  RefreshIcon,
  SearchIcon,
  TrashIcon,
} from "../components/icons";
import { formatRelativeTime } from "../utils/relativeTime";
import "./KnowledgeSources.css";

interface KnowledgeSource {
  id: string;
  type: string;
  source_uri: string | null;
  last_synced_at: string | null;
  chunk_count: number;
  content: string;
}

type SourceType = "manual" | "url" | "pdf";

const PAGE_SIZE = 5;

// Same word-count/overlap the backend's own chunk_text uses
// (app/knowledge/chunking.py) -- kept in sync by hand since there's no
// shared config between the two, so the "Estimated chunks" preview
// below actually matches what the real POST will produce, not a rough
// guess. Word count, not tokens, for the same reason the backend picked
// it: no tokenizer library on either side.
const CHUNK_SIZE_WORDS = 300;
const CHUNK_OVERLAP_WORDS = 50;

function estimateChunkCount(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 0;
  if (words.length <= CHUNK_SIZE_WORDS) return 1;
  const step = CHUNK_SIZE_WORDS - CHUNK_OVERLAP_WORDS;
  return Math.ceil((words.length - CHUNK_SIZE_WORDS) / step) + 1;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// A source has no dedicated title field (docs/ARCHITECTURE.md's data
// model never grew one) -- derived instead: source_uri already IS an
// identifying name for url/pdf (the fetch url / original filename), and
// a manual entry falls back to a short snippet of its own content, the
// closest thing it has to a name.
function sourceTitle(source: KnowledgeSource): string {
  if (source.source_uri) return source.source_uri;
  const words = source.content.trim().split(/\s+/).slice(0, 6);
  return words.length > 0 ? `${words.join(" ")}…` : source.content;
}

const TYPE_ICONS: Record<SourceType, ComponentType<SVGProps<SVGSVGElement>>> = {
  manual: FileTextIcon,
  url: GlobeIcon,
  pdf: FileTextIcon,
};

// Reuses existing semantic tokens rather than inventing new ones --
// accent/success/danger already exist app-wide, and danger for pdf
// happens to match how PDF viewers/icons are conventionally colored
// elsewhere, a nice coincidence not a requirement.
const TYPE_COLOR_CLASS: Record<SourceType, string> = {
  manual: "knowledge-sources__type-icon--accent",
  url: "knowledge-sources__type-icon--success",
  pdf: "knowledge-sources__type-icon--danger",
};

const TYPE_ORDER: SourceType[] = ["manual", "url", "pdf"];

const TYPE_LABEL_KEYS: Record<SourceType, string> = {
  manual: "knowledgeSources.typeManual",
  url: "knowledgeSources.typeUrl",
  pdf: "knowledgeSources.typePdf",
};

export default function KnowledgeSources() {
  const { t, i18n } = useTranslation();
  const { token, logout } = useAuth();
  const { enabled: demoModeEnabled } = useDemoModeContext();
  const [sources, setSources] = useState<KnowledgeSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [type, setType] = useState<SourceType>("manual");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  // Bumped after a successful pdf upload to force the (uncontrolled)
  // file input to remount -- <input type="file"> can't have its
  // displayed filename cleared by resetting React state alone, the DOM
  // element owns that itself.
  const [pdfInputKey, setPdfInputKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Library toolbar -- client-side only, filters/paginates the already-
  // loaded `sources` list rather than round-tripping to the backend
  // (there's no server-side search/pagination on GET /knowledge/sources,
  // and a tenant's source count is small enough that this is fine).
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | SourceType>("all");
  const [page, setPage] = useState(1);

  // Expanded-row view/edit state (docs/ROADMAP.md -- "can't see or edit"
  // gap found via live use). At most one row expanded at a time, and
  // edit mode only ever applies to manual/pdf sources -- url sources show
  // their fetched content read-only, since refresh would silently
  // overwrite a hand edit anyway.
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showAllChunks, setShowAllChunks] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [copiedChunkKey, setCopiedChunkKey] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

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

  // Click-outside-closes convention, same as ChannelRail's own
  // .dropdown-menu -- one openMenuId at a time, so this only ever needs
  // to close whichever row's menu is currently open, not track per-row.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!(event.target instanceof Element) || !event.target.closest(".dropdown-menu")) {
        setOpenMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [searchQuery, typeFilter]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (type === "pdf" && !pdfFile) return;
    setFormError(null);
    setSubmitting(true);
    try {
      // pdf goes through a separate endpoint entirely (multipart/form-data,
      // not JSON) -- POST /knowledge/sources itself only ever accepts
      // manual/url (app/knowledge/api.py's CreateKnowledgeSourceRequest).
      let created: KnowledgeSource;
      if (type === "pdf") {
        const formData = new FormData();
        formData.append("file", pdfFile as File);
        created = await apiPostFile<KnowledgeSource>("/knowledge/sources/pdf", formData, token);
      } else {
        const body = type === "manual" ? { type, content } : { type, url };
        created = await apiPost<KnowledgeSource>("/knowledge/sources", body, token);
      }
      setSources((current) => (current ? [created, ...current] : [created]));
      setContent("");
      setUrl("");
      setPdfFile(null);
      setPdfInputKey((current) => current + 1);
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

  async function handleRefreshAll() {
    const refreshable = (sources ?? []).filter((source) => source.type === "url");
    if (refreshable.length === 0) return;
    setError(null);
    setRefreshingAll(true);
    try {
      // Sequential, not Promise.all -- these hit real external urls, no
      // need to fire them all at once, and a stray 401 partway through
      // should stop the whole batch rather than firing the rest anyway.
      for (const source of refreshable) {
        const updated = await apiPost<KnowledgeSource>(
          `/knowledge/sources/${source.id}/refresh`,
          undefined,
          token,
        );
        setSources((current) => current?.map((row) => (row.id === source.id ? updated : row)) ?? null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : t("knowledgeSources.refreshError"));
    } finally {
      setRefreshingAll(false);
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

  function toggleExpanded(source: KnowledgeSource) {
    setOpenMenuId(null);
    if (expandedId === source.id) {
      setExpandedId(null);
      setEditingId(null);
      return;
    }
    setExpandedId(source.id);
    setEditingId(null);
    setShowAllChunks(false);
  }

  function startEditing(source: KnowledgeSource) {
    setOpenMenuId(null);
    setExpandedId(source.id);
    setEditingId(source.id);
    setEditContent(source.content);
    setEditError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setEditError(null);
  }

  async function handleSaveEdit(id: string) {
    setEditError(null);
    setSavingId(id);
    try {
      const updated = await apiPut<KnowledgeSource>(
        `/knowledge/sources/${id}`,
        { content: editContent },
        token,
      );
      setSources((current) => current?.map((row) => (row.id === id ? updated : row)) ?? null);
      setEditingId(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setEditError(err instanceof ApiError ? err.message : t("knowledgeSources.editError"));
    } finally {
      setSavingId(null);
    }
  }

  function handleCopyChunk(key: string, text: string) {
    void navigator.clipboard.writeText(text);
    setCopiedChunkKey(key);
    setTimeout(() => setCopiedChunkKey((current) => (current === key ? null : current)), 1500);
  }

  const totalSources = sources?.length ?? 0;
  const totalChunks = sources?.reduce((sum, source) => sum + source.chunk_count, 0) ?? 0;
  const totalBytes =
    sources?.reduce((sum, source) => sum + new Blob([source.content]).size, 0) ?? 0;
  const lastSyncedAt =
    sources?.reduce<string | null>((latest, source) => {
      if (!source.last_synced_at) return latest;
      if (!latest || new Date(source.last_synced_at) > new Date(latest)) {
        return source.last_synced_at;
      }
      return latest;
    }, null) ?? null;
  const refreshableCount = sources?.filter((source) => source.type === "url").length ?? 0;

  const estimatedChunks = type === "manual" ? estimateChunkCount(content) : null;

  const filteredSources = (sources ?? []).filter((source) => {
    if (typeFilter !== "all" && source.type !== typeFilter) return false;
    const query = searchQuery.trim().toLowerCase();
    if (!query) return true;
    return (
      sourceTitle(source).toLowerCase().includes(query) ||
      source.content.toLowerCase().includes(query)
    );
  });
  const totalPages = Math.max(1, Math.ceil(filteredSources.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedSources = filteredSources.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.knowledge")}</h1>
        <button
          type="button"
          className="button"
          disabled={demoModeEnabled || refreshingAll || refreshableCount === 0}
          onClick={() => void handleRefreshAll()}
          title={demoModeEnabled ? t("demoMode.disabledTooltip") : t("knowledgeSources.refreshAllHint")}
        >
          <RefreshIcon />
          {refreshingAll ? t("knowledgeSources.refreshing") : t("knowledgeSources.refreshAll")}
        </button>
      </div>
      <p className="page__description">{t("pages.knowledge")}</p>

      <div className="knowledge-sources__stats">
        <div className="card knowledge-sources__stat">
          <span className="knowledge-sources__stat-icon knowledge-sources__stat-icon--accent">
            <FileTextIcon />
          </span>
          <div>
            <div className="knowledge-sources__stat-label">{t("knowledgeSources.statSources")}</div>
            <div className="knowledge-sources__stat-value">{totalSources}</div>
            <div className="knowledge-sources__stat-sublabel">
              {t("knowledgeSources.statSourcesSub")}
            </div>
          </div>
        </div>
        <div className="card knowledge-sources__stat">
          <span className="knowledge-sources__stat-icon knowledge-sources__stat-icon--info">
            <LayersIcon />
          </span>
          <div>
            <div className="knowledge-sources__stat-label">{t("knowledgeSources.statChunks")}</div>
            <div className="knowledge-sources__stat-value">{totalChunks}</div>
            <div className="knowledge-sources__stat-sublabel">
              {t("knowledgeSources.statChunksSub")}
            </div>
          </div>
        </div>
        <div className="card knowledge-sources__stat">
          <span className="knowledge-sources__stat-icon knowledge-sources__stat-icon--success">
            <DatabaseIcon />
          </span>
          <div>
            <div className="knowledge-sources__stat-label">{t("knowledgeSources.statStorage")}</div>
            <div className="knowledge-sources__stat-value">{formatBytes(totalBytes)}</div>
            <div className="knowledge-sources__stat-sublabel">
              {t("knowledgeSources.statStorageSub")}
            </div>
          </div>
        </div>
        <div className="card knowledge-sources__stat">
          <span className="knowledge-sources__stat-icon knowledge-sources__stat-icon--warning">
            <ClockIcon />
          </span>
          <div>
            <div className="knowledge-sources__stat-label">{t("knowledgeSources.statLastSync")}</div>
            <div className="knowledge-sources__stat-value">
              {lastSyncedAt
                ? formatRelativeTime(lastSyncedAt, i18n.language, t("time.justNow"))
                : "—"}
            </div>
            <div className="knowledge-sources__stat-sublabel">
              {t("knowledgeSources.statLastSyncSub")}
            </div>
          </div>
        </div>
      </div>

      <div className="card knowledge-sources__panel">
        <h2 className="knowledge-sources__panel-title">{t("knowledgeSources.addTitle")}</h2>
        <p className="knowledge-sources__panel-description">
          {t("knowledgeSources.addDescription")}
        </p>

        <div className="tabs knowledge-sources__type-tabs" role="tablist">
          {TYPE_ORDER.map((option) => {
            const OptionIcon = TYPE_ICONS[option];
            return (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={type === option}
                className={`tabs__tab${type === option ? " tabs__tab--active" : ""}`}
                onClick={() => setType(option)}
              >
                <OptionIcon className="tabs__tab-icon" />
                {t(TYPE_LABEL_KEYS[option])}
              </button>
            );
          })}
        </div>

        <form className="form knowledge-sources__add-form" onSubmit={(event) => void handleSubmit(event)}>
          {type === "manual" && (
            <label className="form__field">
              {t("knowledgeSources.content")}
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={t("knowledgeSources.contentPlaceholder")}
                required
              />
            </label>
          )}
          {type === "url" && (
            <label className="form__field">
              {t("knowledgeSources.url")}
              <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} required />
            </label>
          )}
          {type === "pdf" && (
            <label className="form__field">
              {t("knowledgeSources.pdfFile")}
              <input
                key={pdfInputKey}
                type="file"
                accept="application/pdf"
                onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
                required
              />
            </label>
          )}

          <div className="knowledge-sources__add-footer">
            <span className="knowledge-sources__estimate">
              {estimatedChunks !== null
                ? t("knowledgeSources.estimatedChunks", { count: estimatedChunks })
                : " "}
            </span>
            <button
              type="submit"
              className="button button--primary"
              disabled={demoModeEnabled || submitting}
              title={demoModeEnabled ? t("demoMode.disabledTooltip") : undefined}
            >
              {submitting ? t("knowledgeSources.adding") : t("knowledgeSources.add")}
            </button>
          </div>
          {formError && (
            <p className="error-message" role="alert">
              {formError}
            </p>
          )}
        </form>
      </div>

      <div className="knowledge-sources__library-header">
        <div>
          <h2 className="knowledge-sources__panel-title">{t("knowledgeSources.libraryTitle")}</h2>
          <p className="knowledge-sources__panel-description">
            {t("knowledgeSources.libraryDescription")}
          </p>
        </div>
        <div className="knowledge-sources__library-toolbar">
          <label className="knowledge-sources__search">
            <SearchIcon />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("knowledgeSources.searchPlaceholder")}
              aria-label={t("knowledgeSources.searchPlaceholder")}
            />
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as "all" | SourceType)}
            aria-label={t("knowledgeSources.filterAllTypes")}
          >
            <option value="all">{t("knowledgeSources.filterAllTypes")}</option>
            <option value="manual">{t("knowledgeSources.typeManual")}</option>
            <option value="url">{t("knowledgeSources.typeUrl")}</option>
            <option value="pdf">{t("knowledgeSources.typePdf")}</option>
          </select>
        </div>
      </div>

      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {sources === null && !error && <p>{t("knowledgeSources.loading")}</p>}
      {sources !== null && sources.length === 0 && (
        <div className="empty-state">{t("knowledgeSources.empty")}</div>
      )}
      {sources !== null && sources.length > 0 && filteredSources.length === 0 && (
        <div className="empty-state">{t("knowledgeSources.noMatches")}</div>
      )}

      {pagedSources.length > 0 && (
        <ul className="knowledge-sources__list">
          {pagedSources.map((source) => {
            const sourceType = (source.type as SourceType) in TYPE_ICONS
              ? (source.type as SourceType)
              : "manual";
            const TypeIcon = TYPE_ICONS[sourceType];
            const isExpanded = expandedId === source.id;
            const chunks = source.content.split("\n\n");
            const visibleChunks = showAllChunks ? chunks : chunks.slice(0, 3);
            return (
              <li key={source.id} className="card knowledge-sources__row">
                <div className="knowledge-sources__row-main">
                  <span
                    className={`knowledge-sources__type-icon ${TYPE_COLOR_CLASS[sourceType]}`}
                  >
                    <TypeIcon />
                  </span>
                  <div className="knowledge-sources__row-title">
                    <strong>{sourceTitle(source)}</strong>
                    <span>{t(TYPE_LABEL_KEYS[sourceType])}</span>
                  </div>
                  <div className="knowledge-sources__row-stat">
                    <div>{source.chunk_count}</div>
                    <span>{t("knowledgeSources.chunkCount")}</span>
                  </div>
                  <div className="knowledge-sources__row-stat">
                    <div>
                      {source.last_synced_at
                        ? formatRelativeTime(source.last_synced_at, i18n.language, t("time.justNow"))
                        : "—"}
                    </div>
                    <span>{t("knowledgeSources.lastSynced")}</span>
                  </div>
                  <span className="knowledge-sources__ready-badge">
                    {t("knowledgeSources.statusReady")}
                  </span>
                  <button
                    type="button"
                    className="button"
                    onClick={() => toggleExpanded(source)}
                    aria-label={isExpanded ? t("knowledgeSources.hide") : t("knowledgeSources.view")}
                    title={isExpanded ? t("knowledgeSources.hide") : t("knowledgeSources.view")}
                  >
                    <ChevronIcon className={`chevron${isExpanded ? " chevron--expanded" : ""}`} />
                  </button>
                  <div className="dropdown-menu">
                    <button
                      type="button"
                      className="button"
                      aria-label={t("knowledgeSources.actions")}
                      aria-expanded={openMenuId === source.id}
                      onClick={() =>
                        setOpenMenuId((current) => (current === source.id ? null : source.id))
                      }
                    >
                      <MoreIcon />
                    </button>
                    {openMenuId === source.id && (
                      <div className="dropdown-menu__list">
                        {(sourceType === "manual" || sourceType === "pdf") && (
                          <button
                            type="button"
                            className="dropdown-menu__item"
                            onClick={() => startEditing(source)}
                          >
                            <PencilIcon className="dropdown-menu__item-icon" />
                            {t("knowledgeSources.edit")}
                          </button>
                        )}
                        {sourceType === "url" && (
                          <button
                            type="button"
                            className="dropdown-menu__item"
                            disabled={demoModeEnabled || refreshingId === source.id}
                            title={demoModeEnabled ? t("demoMode.disabledTooltip") : undefined}
                            onClick={() => {
                              setOpenMenuId(null);
                              void handleRefresh(source.id);
                            }}
                          >
                            <RefreshIcon className="dropdown-menu__item-icon" />
                            {refreshingId === source.id
                              ? t("knowledgeSources.refreshing")
                              : t("knowledgeSources.refresh")}
                          </button>
                        )}
                        <button
                          type="button"
                          className="dropdown-menu__item dropdown-menu__item--danger"
                          disabled={demoModeEnabled || deletingId === source.id}
                          title={demoModeEnabled ? t("demoMode.disabledTooltip") : undefined}
                          onClick={() => {
                            setOpenMenuId(null);
                            void handleDelete(source.id);
                          }}
                        >
                          <TrashIcon className="dropdown-menu__item-icon" />
                          {t("knowledgeSources.delete")}
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="knowledge-sources__expanded">
                    {editingId === source.id ? (
                      <div className="form__field">
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          rows={6}
                        />
                        <div className="knowledge-sources__edit-actions">
                          <button
                            type="button"
                            className="button button--primary"
                            disabled={demoModeEnabled || savingId === source.id}
                            title={demoModeEnabled ? t("demoMode.disabledTooltip") : undefined}
                            onClick={() => void handleSaveEdit(source.id)}
                          >
                            {savingId === source.id
                              ? t("knowledgeSources.saving")
                              : t("knowledgeSources.save")}
                          </button>
                          <button
                            type="button"
                            className="button"
                            disabled={savingId === source.id}
                            onClick={cancelEditing}
                          >
                            {t("knowledgeSources.cancel")}
                          </button>
                        </div>
                        {editError && (
                          <p className="error-message" role="alert">
                            {editError}
                          </p>
                        )}
                      </div>
                    ) : (
                      <>
                        <h3 className="knowledge-sources__chunks-title">
                          {t("knowledgeSources.chunkPreview", { count: chunks.length })}
                        </h3>
                        <ul className="knowledge-sources__chunks">
                          {visibleChunks.map((chunk, index) => {
                            const key = `${source.id}-${index}`;
                            return (
                              <li key={key} className="knowledge-sources__chunk">
                                <span className="knowledge-sources__chunk-label">
                                  {t("knowledgeSources.chunkLabel", { index: index + 1 })}
                                </span>
                                <span className="knowledge-sources__chunk-text">{chunk}</span>
                                <button
                                  type="button"
                                  className="knowledge-sources__chunk-copy"
                                  onClick={() => handleCopyChunk(key, chunk)}
                                  aria-label={t("knowledgeSources.copyChunk")}
                                  title={t("knowledgeSources.copyChunk")}
                                >
                                  {copiedChunkKey === key ? <CheckIcon /> : <CopyIcon />}
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                        {chunks.length > 3 && (
                          <button
                            type="button"
                            className="knowledge-sources__view-all"
                            onClick={() => setShowAllChunks((current) => !current)}
                          >
                            {showAllChunks
                              ? t("knowledgeSources.showFewerChunks")
                              : t("knowledgeSources.viewAllChunks", { count: chunks.length })}
                            <ChevronIcon
                              className={`chevron${showAllChunks ? " chevron--expanded" : ""}`}
                            />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {filteredSources.length > 0 && (
        <div className="knowledge-sources__pagination">
          <span className="knowledge-sources__pagination-summary">
            {t("knowledgeSources.paginationSummary", {
              from: (currentPage - 1) * PAGE_SIZE + 1,
              to: Math.min(currentPage * PAGE_SIZE, filteredSources.length),
              total: filteredSources.length,
            })}
          </span>
          <div className="knowledge-sources__pagination-pages">
            <button
              type="button"
              className="button"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
              aria-label={t("knowledgeSources.previousPage")}
            >
              <ChevronIcon className="chevron chevron--left" />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((pageNumber) => (
              <button
                key={pageNumber}
                type="button"
                className={`button${pageNumber === currentPage ? " button--primary" : ""}`}
                onClick={() => setPage(pageNumber)}
              >
                {pageNumber}
              </button>
            ))}
            <button
              type="button"
              className="button"
              disabled={currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
              aria-label={t("knowledgeSources.nextPage")}
            >
              <ChevronIcon className="chevron" />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
