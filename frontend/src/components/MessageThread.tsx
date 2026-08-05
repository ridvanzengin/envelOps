import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTick } from "../hooks/useTick";
import { formatRelativeTime } from "../utils/relativeTime";
import type { Escalation, Message } from "../context/conversationPanel/context";
import { useDemoModeContext } from "../context/demoMode/useDemoModeContext";
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
  // TestConsole only (docs/ROADMAP.md test console polish): an inbound
  // message already sent to the backend but not yet reflected in
  // `messages` -- shown immediately on submit (optimistic send) instead of
  // waiting for the full pipeline round-trip, which can take several
  // seconds (up to 4 sequential Gemini calls, CLAUDE.md).
  pendingInbound?: string | null;
  // True while the pipeline is still running for `pendingInbound` --
  // renders a "Thinking..." placeholder where the AI's reply will appear,
  // replacing the old approach of disabling the Send button with
  // "Sending...".
  thinking?: boolean;
}

// The pipeline genuinely does run through these steps in this order (see
// Documentation.tsx's own "intake → intent → ground → score → decide →
// reply → log → follow-up" stat, and CLAUDE.md's "up to 4 sequential LLM
// calls per inbound message") -- a real round trip easily takes several
// seconds, so a static "Thinking..." bubble that never changes reads as
// hung, not working. Cycling through the actual step names (not generic
// filler) gives continuous feedback that's also true, not just decorative.
const THINKING_PHRASE_KEYS = [
  "testConsole.thinking.understandingIntent",
  "testConsole.thinking.groundingInKnowledge",
  "testConsole.thinking.scoringLead",
  "testConsole.thinking.decidingNextStep",
] as const;
const THINKING_PHRASE_INTERVAL_MS = 1800;

function ThinkingIndicator() {
  const { t } = useTranslation();
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setIndex((prev) => (prev + 1) % THINKING_PHRASE_KEYS.length);
    }, THINKING_PHRASE_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  return <span className="conversation-panel__thinking">{t(THINKING_PHRASE_KEYS[index])}</span>;
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
  pendingInbound,
  thinking,
}: MessageThreadProps) {
  const { t, i18n } = useTranslation();
  const { enabled: demoModeEnabled } = useDemoModeContext();
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
                    disabled={demoModeEnabled || resolvingEscalationId === escalation.id}
                    title={demoModeEnabled ? t("demoMode.disabledTooltip") : undefined}
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
      {pendingInbound != null && (
        <li className="conversation-panel__message-group conversation-panel__message-group--inbound">
          <div className="conversation-panel__message conversation-panel__message--inbound">
            {pendingInbound}
          </div>
        </li>
      )}
      {thinking && (
        <li className="conversation-panel__message-group conversation-panel__message-group--outbound">
          <div className="conversation-panel__message conversation-panel__message--outbound">
            <ThinkingIndicator />
          </div>
        </li>
      )}
    </ul>
  );
}
