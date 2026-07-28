import type { Message } from "../context/conversationPanel/context";
import { DiagnosticsBadges } from "./DiagnosticsBadges";

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
