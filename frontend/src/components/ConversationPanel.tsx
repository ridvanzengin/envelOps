import { useTranslation } from "react-i18next";

import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { ChevronLeftIcon, CheckIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";
import "./ConversationPanel.css";

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
    <aside className="conversation-panel">
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
      )}
    </aside>
  );
}
