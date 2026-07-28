import { useTranslation } from "react-i18next";

import type { Message, MessageDiagnostics } from "../context/conversationPanel/context";

// Shared between ConversationPanel's thread view and TestConsole -- both
// need identical direction-based bubble rendering, just fed from a
// different data source (a selected real/test conversation vs. the Test
// Console's own single always-known conversation per channel).
export function MessageThread({ messages }: { messages: Message[] }) {
  return (
    <ul className="conversation-panel__thread">
      {messages.map((message) => (
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
        </li>
      ))}
    </ul>
  );
}

// Test Console only (docs/ROADMAP.md §3.4) -- surfaces the pipeline's own
// reasoning for this inbound message (intent/lead score/next-step
// decision) so the tenant owner can debug why the AI replied the way it
// did, message by message, not just read the final reply.
function DiagnosticsBadges({ diagnostics }: { diagnostics: MessageDiagnostics }) {
  const { t } = useTranslation();
  return (
    <div className="message-diagnostics">
      {diagnostics.detected_intent && (
        <span className="message-diagnostics__badge">
          {t(
            `testConsole.diagnostics.intent.${diagnostics.detected_intent}`,
            diagnostics.detected_intent,
          )}
        </span>
      )}
      {diagnostics.lead_score && (
        <span
          className={`message-diagnostics__badge message-diagnostics__badge--score-${diagnostics.lead_score}`}
        >
          {t(
            `testConsole.diagnostics.score.${diagnostics.lead_score}`,
            diagnostics.lead_score,
          )}
        </span>
      )}
      {diagnostics.decision && (
        <span
          className={`message-diagnostics__badge message-diagnostics__badge--decision-${diagnostics.decision}`}
        >
          {t(
            `testConsole.diagnostics.decision.${diagnostics.decision}`,
            diagnostics.decision,
          )}
        </span>
      )}
    </div>
  );
}
