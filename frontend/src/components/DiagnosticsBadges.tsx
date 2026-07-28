import { useTranslation } from "react-i18next";

import type { MessageDiagnostics } from "../context/conversationPanel/context";

// Shared between MessageThread (per-message, Test Console only so far,
// docs/ROADMAP.md §3.4) and ConversationPanel's row list (per-conversation,
// real + test channels, §3.3) -- both just render whichever of
// intent/lead-score/decision are present, so a caller that doesn't have a
// `decision` (the rail only ever has intent+lead-score) simply omits it
// rather than needing a separate component.
export function DiagnosticsBadges({ diagnostics }: { diagnostics: MessageDiagnostics }) {
  const { t } = useTranslation();
  return (
    <div className="diagnostics-badges">
      {diagnostics.detected_intent && (
        <span className="diagnostics-badge">
          {t(`diagnostics.intent.${diagnostics.detected_intent}`, diagnostics.detected_intent)}
        </span>
      )}
      {diagnostics.lead_score && (
        <span
          className={`diagnostics-badge diagnostics-badge--score-${diagnostics.lead_score}`}
        >
          {t(`diagnostics.score.${diagnostics.lead_score}`, diagnostics.lead_score)}
        </span>
      )}
      {diagnostics.decision && (
        <span
          className={`diagnostics-badge diagnostics-badge--decision-${diagnostics.decision}`}
        >
          {t(`diagnostics.decision.${diagnostics.decision}`, diagnostics.decision)}
        </span>
      )}
    </div>
  );
}
