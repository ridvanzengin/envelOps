import { useTranslation } from "react-i18next";

import { useTick } from "../hooks/useTick";
import { formatRelativeTime } from "../utils/relativeTime";
import type { Escalation, Message } from "../context/conversationPanel/context";
import { CheckIcon } from "./icons";
import { DiagnosticsBadges } from "./DiagnosticsBadges";

interface MessageThreadProps {
  messages: Message[];
  // All optional -- TestConsole shares this component but keeps its own
  // top-level escalatedNotice banner as the resolve mechanism instead
  // (docs/ROADMAP.md §3.1), so it never passes these.
  escalationById?: Map<string, Escalation>;
  onResolveEscalation?: (escalationId: string) => void;
  resolvingEscalationId?: string | null;
}

// Shared between ConversationPanel's thread view and TestConsole -- both
// need identical direction-based bubble rendering, just fed from a
// different data source (a selected real/test conversation vs. the Test
// Console's own single always-known conversation per channel).
export function MessageThread({
  messages,
  escalationById,
  onResolveEscalation,
  resolvingEscalationId,
}: MessageThreadProps) {
  const { t, i18n } = useTranslation();
  // Re-renders every 60s so relative timestamps ("5m ago") don't go stale
  // while the thread stays open -- the tick value itself is unused, its
  // only job is to force this component to re-evaluate formatRelativeTime.
  useTick(60_000);

  return (
    <ul className="conversation-panel__thread">
      {messages.map((message) => {
        if (message.audience === "internal") {
          const escalation = message.escalation_id
            ? escalationById?.get(message.escalation_id)
            : undefined;
          const canResolve =
            onResolveEscalation !== undefined && escalation?.status === "pending";
          return (
            <li key={message.id} className="conversation-panel__message-group--internal">
              <div className="conversation-panel__internal-note">
                <div className="conversation-panel__internal-note-header">
                  <span className="conversation-panel__internal-note-sender">
                    {t("conversationPanel.internalNoteSender")}
                  </span>
                  <span className="conversation-panel__message-time">
                    {formatRelativeTime(
                      message.created_at,
                      i18n.language,
                      t("time.justNow"),
                    )}
                  </span>
                </div>
                <div className="conversation-panel__internal-note-text">{message.text}</div>
                {canResolve && (
                  <button
                    type="button"
                    className="button button--primary conversation-panel__internal-note-resolve"
                    disabled={resolvingEscalationId === escalation.id}
                    onClick={() => onResolveEscalation(escalation.id)}
                  >
                    <CheckIcon />
                    {resolvingEscalationId === escalation.id
                      ? t("escalations.resolving")
                      : t("escalations.resolve")}
                  </button>
                )}
              </div>
            </li>
          );
        }

        return (
          <li
            key={message.id}
            className={`conversation-panel__message-group conversation-panel__message-group--${message.direction}`}
          >
            {message.diagnostics && <DiagnosticsBadges diagnostics={message.diagnostics} />}
            <div
              className={`conversation-panel__message conversation-panel__message--${message.direction}`}
            >
              {message.text}
            </div>
            <span className="conversation-panel__message-time">
              {formatRelativeTime(message.created_at, i18n.language, t("time.justNow"))}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
