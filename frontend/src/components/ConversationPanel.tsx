import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { ChevronLeftIcon, CheckIcon, SendIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";
import "./ConversationPanel.css";

const WIDTH_STORAGE_KEY = "envelops:conversation-panel-width";
const DEFAULT_WIDTH = 340;
const MIN_WIDTH = 280;
const MAX_WIDTH = 640;

function loadStoredWidth(): number {
  const raw = typeof window !== "undefined" ? window.localStorage.getItem(WIDTH_STORAGE_KEY) : null;
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, parsed)) : DEFAULT_WIDTH;
}

export function ConversationPanel() {
  const { t } = useTranslation();
  const {
    isOpen,
    closePanel,
    conversations,
    conversationsError,
    escalationByConversationId,
    escalatedOnly,
    setEscalatedOnly,
    selectedConversationId,
    selectConversation,
    backToList,
    messages,
    threadError,
    resolveEscalation,
    resolvingEscalationId,
    resolveError,
  } = useConversationPanel();

  // Persists across reopens and reloads, same drag-to-resize convention as
  // the sibling reference project's own right-side panel -- the handle
  // sits on the panel's *left* edge, so width tracks the distance from the
  // viewport's right edge to the cursor, not raw clientX.
  const [width, setWidth] = useState(loadStoredWidth);
  const resizingRef = useRef(false);

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
  const selectedEscalation = selectedConversationId
    ? (escalationByConversationId.get(selectedConversationId) ?? null)
    : null;

  const visibleConversations = escalatedOnly
    ? (conversations?.filter((conversation) =>
        escalationByConversationId.has(conversation.id),
      ) ?? null)
    : conversations;

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
            ? (selectedConversation?.external_contact_id ?? t("channelRail.telegram"))
            : t("channelRail.telegram")}
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
          {escalationByConversationId.size > 0 && (
            <button
              type="button"
              className={`conversation-panel__filter${
                escalatedOnly ? " conversation-panel__filter--active" : ""
              }`}
              onClick={() => setEscalatedOnly(!escalatedOnly)}
            >
              {t("conversationPanel.filterEscalated")}
              <span className="conversation-panel__filter-count">
                {escalationByConversationId.size}
              </span>
            </button>
          )}

          {conversationsError && <p className="conversation-panel__hint" role="alert">{conversationsError}</p>}
          {conversations === null && !conversationsError && (
            <p className="conversation-panel__hint">{t("conversationPanel.loading")}</p>
          )}
          {visibleConversations !== null && visibleConversations.length === 0 && (
            <p className="conversation-panel__hint">{t("conversationPanel.empty")}</p>
          )}
          {visibleConversations !== null && visibleConversations.length > 0 && (
            <ul className="conversation-panel__list">
              {visibleConversations.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    className="conversation-panel__row"
                    onClick={() => selectConversation(conversation.id)}
                  >
                    <div className="conversation-panel__row-top">
                      <strong>{conversation.external_contact_id}</strong>
                      <StatusBadge status={conversation.status} />
                    </div>
                    <div className="conversation-panel__row-preview">
                      {conversation.last_message_text ?? t("conversationPanel.noMessages")}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <>
          <div className="conversation-panel__body">
            {selectedEscalation && (
              <div className="conversation-panel__escalation">
                <div className="conversation-panel__escalation-reason">
                  {selectedEscalation.reason}
                </div>
                <button
                  type="button"
                  className="button button--primary conversation-panel__resolve"
                  disabled={resolvingEscalationId === selectedEscalation.id}
                  onClick={() => void resolveEscalation(selectedEscalation.id)}
                >
                  <CheckIcon />
                  {resolvingEscalationId === selectedEscalation.id
                    ? t("escalations.resolving")
                    : t("escalations.resolve")}
                </button>
                {resolveError && <p className="conversation-panel__hint" role="alert">{resolveError}</p>}
              </div>
            )}

            {threadError && <p className="conversation-panel__hint" role="alert">{threadError}</p>}
            {messages === null && !threadError && (
              <p className="conversation-panel__hint">{t("conversationPanel.threadLoading")}</p>
            )}
            {messages !== null && (
              <ul className="conversation-panel__thread">
                {messages.map((message) => (
                  <li
                    key={message.id}
                    className={`conversation-panel__message conversation-panel__message--${message.direction}`}
                  >
                    {message.text}
                  </li>
                ))}
              </ul>
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
