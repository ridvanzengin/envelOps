import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Conversation, ConversationFilterKey } from "../context/conversationPanel/context";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useTick } from "../hooks/useTick";
import { formatRelativeTime } from "../utils/relativeTime";
import { DiagnosticsBadges } from "./DiagnosticsBadges";
import { ChevronLeftIcon, SendIcon } from "./icons";
import { MessageThread } from "./MessageThread";
import "./ConversationPanel.css";

// One entry per rail filter chip (docs/ROADMAP.md UI polish pass) --
// `match` decides both which conversations a chip filters to AND (via
// escalationByConversationId, the one predicate that isn't a plain field
// read) whether a given conversation counts for that chip's badge count.
// Order here is render order: the escalation-state pair first (highest-
// priority signal, same position the old single filter button occupied),
// then the intent/score-based tags.
const FILTER_DEFINITIONS: {
  key: ConversationFilterKey;
  labelKey: string;
  match: (conversation: Conversation, escalatedIds: Set<string>) => boolean;
}[] = [
  {
    key: "escalated",
    labelKey: "conversationPanel.filterEscalated",
    match: (conversation, escalatedIds) => escalatedIds.has(conversation.id),
  },
  {
    key: "unescalated",
    labelKey: "conversationPanel.filterUnescalated",
    match: (conversation, escalatedIds) => !escalatedIds.has(conversation.id),
  },
  {
    key: "hot_lead",
    labelKey: "conversationPanel.filterHotLead",
    match: (conversation) => conversation.lead_score === "hot",
  },
  {
    key: "purchase_intent",
    labelKey: "diagnostics.intent.purchase_intent",
    match: (conversation) => conversation.detected_intent === "purchase_intent",
  },
  {
    key: "complaint",
    labelKey: "diagnostics.intent.complaint_or_problem",
    match: (conversation) => conversation.detected_intent === "complaint_or_problem",
  },
];

const WIDTH_STORAGE_KEY = "envelops:conversation-panel-width";
const DEFAULT_WIDTH = 340;
const MIN_WIDTH = 280;
const MAX_WIDTH = 640;

// Client-side only -- GET /conversations already returns the whole
// channel's list in one response (no backend offset/limit param exists),
// this just slices what's already in memory so a long list doesn't turn
// the rail into one giant scroll.
const CONVERSATIONS_PAGE_SIZE = 20;

function loadStoredWidth(): number {
  const raw = typeof window !== "undefined" ? window.localStorage.getItem(WIDTH_STORAGE_KEY) : null;
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, parsed)) : DEFAULT_WIDTH;
}

export function ConversationPanel() {
  const { t, i18n } = useTranslation();
  const {
    isOpen,
    activeChannelType,
    closePanel,
    conversations,
    conversationsError,
    escalationByConversationId,
    escalationById,
    activeFilter,
    toggleFilter,
    selectedConversationId,
    selectConversation,
    backToList,
    messages,
    threadError,
    resolveEscalation,
    resolvingEscalationId,
    resolveError,
  } = useConversationPanel();
  // Keeps conversation-list row timestamps live, same as MessageThread's
  // own tick for its per-message timestamps.
  useTick(60_000);

  // Persists across reopens and reloads, same drag-to-resize convention as
  // the sibling reference project's own right-side panel -- the handle
  // sits on the panel's *left* edge, so width tracks the distance from the
  // viewport's right edge to the cursor, not raw clientX.
  const [width, setWidth] = useState(loadStoredWidth);
  const resizingRef = useRef(false);

  // 1-indexed. Reset whenever the channel or the active filter changes --
  // landing on page 3 of a *different* platform's list (or of a newly
  // selected filter) would look like a bug, same reasoning as openPanel
  // resetting selectedConversationId on a platform swap. Deliberately
  // NOT reset on every `conversations` refetch (a live SSE update
  // shouldn't yank someone reading page 2 back to page 1); the clamp
  // below guards against that leaving `page` out of bounds instead.
  const [page, setPage] = useState(1);
  useEffect(() => {
    setPage(1);
  }, [activeChannelType, activeFilter]);

  useEffect(() => {
    function handleMouseMove(event: MouseEvent) {
      if (!resizingRef.current) return;
      const next = window.innerWidth - event.clientX;
      setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, next)));
    }
    function handleMouseUp() {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(WIDTH_STORAGE_KEY, String(width));
  }, [width]);

  function handleResizeStart() {
    resizingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  if (!isOpen) return null;

  const selectedConversation =
    conversations?.find((conversation) => conversation.id === selectedConversationId) ?? null;

  const escalatedIds = new Set(escalationByConversationId.keys());

  // Counts within the currently loaded (single-channel) conversation
  // list, not tenant-wide -- a count bigger than what the chip's own
  // filter reveals would be confusing. Computed regardless of
  // activeFilter (every chip always shows how many conversations it
  // *would* match, not just the currently-selected one).
  const filterCounts = new Map(
    FILTER_DEFINITIONS.map(({ key, match }) => [
      key,
      conversations?.filter((conversation) => match(conversation, escalatedIds)).length ?? 0,
    ]),
  );

  // Exclusive -- selecting a chip shows ONLY conversations matching that
  // one, cancelling out any previously active chip (direct instruction),
  // not broadening the list to an OR across several.
  const activeFilterDefinition = FILTER_DEFINITIONS.find(({ key }) => key === activeFilter);
  const visibleConversations =
    activeFilterDefinition === undefined
      ? conversations
      : (conversations?.filter((conversation) =>
          activeFilterDefinition.match(conversation, escalatedIds),
        ) ?? null);

  const totalPages = Math.max(
    1,
    Math.ceil((visibleConversations?.length ?? 0) / CONVERSATIONS_PAGE_SIZE),
  );
  // Clamped rather than trusted -- `page` can only be reset via the effect
  // above (channel/filter change), so a background refetch that shrinks
  // the list (e.g. a conversation no longer matching an active filter)
  // could otherwise leave `page` pointing past the end.
  const currentPage = Math.min(page, totalPages);
  const pagedConversations = visibleConversations?.slice(
    (currentPage - 1) * CONVERSATIONS_PAGE_SIZE,
    currentPage * CONVERSATIONS_PAGE_SIZE,
  );

  return (
    <aside className="conversation-panel" style={{ width }}>
      <div className="conversation-panel__resize-handle" onMouseDown={handleResizeStart} />
      <div className="conversation-panel__header">
        {selectedConversationId !== null && (
          <button
            type="button"
            className="conversation-panel__back"
            onClick={backToList}
            aria-label={t("conversationPanel.back")}
          >
            <ChevronLeftIcon />
          </button>
        )}
        <span className="conversation-panel__title">
          {selectedConversationId !== null
            ? (selectedConversation?.external_contact_id ?? t(`channelRail.${activeChannelType}`))
            : t(`channelRail.${activeChannelType}`)}
        </span>
        <button
          type="button"
          className="conversation-panel__close"
          onClick={closePanel}
          aria-label={t("conversationPanel.close")}
        >
          ×
        </button>
      </div>

      {selectedConversationId === null ? (
        <div className="conversation-panel__body">
          {filterCounts.size > 0 && (
            <div className="conversation-panel__filters">
              {FILTER_DEFINITIONS.filter(({ key }) => (filterCounts.get(key) ?? 0) > 0).map(
                ({ key, labelKey }) => (
                  <button
                    key={key}
                    type="button"
                    className={`conversation-panel__filter conversation-panel__filter--${key}${
                      activeFilter === key ? " conversation-panel__filter--active" : ""
                    }`}
                    onClick={() => toggleFilter(key)}
                  >
                    {t(labelKey)}
                    <span className="conversation-panel__filter-count">
                      {filterCounts.get(key)}
                    </span>
                  </button>
                ),
              )}
            </div>
          )}

          {conversationsError && <p className="conversation-panel__hint" role="alert">{conversationsError}</p>}
          {conversations === null && !conversationsError && (
            <p className="conversation-panel__hint">{t("conversationPanel.loading")}</p>
          )}
          {visibleConversations !== null && visibleConversations.length === 0 && (
            <p className="conversation-panel__hint">{t("conversationPanel.empty")}</p>
          )}
          {pagedConversations !== undefined && pagedConversations.length > 0 && (
            <ul className="conversation-panel__list">
              {pagedConversations.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    className="conversation-panel__row"
                    onClick={() => selectConversation(conversation.id)}
                  >
                    <div className="conversation-panel__row-top">
                      <strong>{conversation.external_contact_id}</strong>
                      {escalatedIds.has(conversation.id) && (
                        <span className="conversation-panel__row-badges">
                          <span className="escalated-badge">
                            {t("conversationPanel.filterEscalated")}
                          </span>
                        </span>
                      )}
                    </div>
                    {(conversation.detected_intent || conversation.lead_score) && (
                      <DiagnosticsBadges
                        diagnostics={{
                          detected_intent: conversation.detected_intent,
                          lead_score: conversation.lead_score,
                          decision: null,
                        }}
                      />
                    )}
                    <div className="conversation-panel__row-preview">
                      {conversation.last_message_text ?? t("conversationPanel.noMessages")}
                    </div>
                    {conversation.last_message_at && (
                      <span className="conversation-panel__row-time">
                        {formatRelativeTime(
                          conversation.last_message_at,
                          i18n.language,
                          t("time.justNow"),
                        )}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {totalPages > 1 && (
            <div className="conversation-panel__pagination">
              <button
                type="button"
                className="conversation-panel__page-button"
                onClick={() => setPage(currentPage - 1)}
                disabled={currentPage <= 1}
              >
                {t("conversationPanel.pagePrev")}
              </button>
              <span className="conversation-panel__page-indicator">
                {t("conversationPanel.pageIndicator", { current: currentPage, total: totalPages })}
              </span>
              <button
                type="button"
                className="conversation-panel__page-button"
                onClick={() => setPage(currentPage + 1)}
                disabled={currentPage >= totalPages}
              >
                {t("conversationPanel.pageNext")}
              </button>
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="conversation-panel__body">
            {/* No more top banner -- the escalation reason + Resolve action
                now live inline in the thread itself, on the internal-note
                bubble MessageThread renders (docs/ROADMAP.md §3.1). That
                bubble is always the last message right after an
                escalation, exactly where attention already lands. */}
            {resolveError && <p className="conversation-panel__hint" role="alert">{resolveError}</p>}
            {threadError && <p className="conversation-panel__hint" role="alert">{threadError}</p>}
            {messages === null && !threadError && (
              <p className="conversation-panel__hint">{t("conversationPanel.threadLoading")}</p>
            )}
            {messages !== null && (
              <MessageThread
                messages={messages}
                escalationById={escalationById}
                onResolveEscalation={(escalationId) => void resolveEscalation(escalationId)}
                resolvingEscalationId={resolvingEscalationId}
              />
            )}
          </div>

          {/* Placeholder only -- no backend capability yet for a human to
              send a message outside the pipeline (docs/ARCHITECTURE.md
              §11's deferred pause-mode item). Disabled rather than wired
              to a no-op, so it doesn't look like a silently broken send. */}
          <div className="conversation-panel__input-row">
            <input
              type="text"
              className="conversation-panel__input"
              placeholder={t("conversationPanel.replyPlaceholder")}
              disabled
              title={t("conversationPanel.replyDisabledHint")}
            />
            <button
              type="button"
              className="button button--primary conversation-panel__send"
              disabled
              title={t("conversationPanel.replyDisabledHint")}
              aria-label={t("conversationPanel.replyDisabledHint")}
            >
              <SendIcon />
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
