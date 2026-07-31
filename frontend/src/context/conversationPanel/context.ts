import { createContext } from "react";

// The rail's quick-filter chips (docs/ROADMAP.md UI polish pass) -- each
// one a boolean fact already present on Conversation below, not a new
// backend field. "escalated" reads from escalationByConversationId (a
// conversation doesn't carry its own escalation state directly), the
// other two read straight off detected_intent/lead_score.
//
// Exclusive, not multi-select (direct instruction): clicking a chip
// selects only that filter, cancelling out whatever was active before --
// not a Set of independently-toggled chips ANDed/ORed together.
export type ConversationFilterKey =
  | "escalated"
  | "unescalated"
  | "hot_lead"
  | "purchase_intent"
  | "complaint";

// Latest pipeline_traces row for a message/conversation (docs/ROADMAP.md
// §3.3/§3.4) -- `decision` is only ever populated per-message
// (MessageThread/Test Console); the rail's per-conversation row
// (ConversationPanel) only has intent+lead-score to show.
export interface MessageDiagnostics {
  detected_intent: string | null;
  lead_score: string | null;
  decision: string | null;
}

export interface Conversation {
  id: string;
  external_contact_id: string;
  status: string;
  last_message_text: string | null;
  last_message_at: string | null;
  channel_type: string;
  is_test: boolean;
  detected_intent: string | null;
  lead_score: string | null;
}

export interface Message {
  id: string;
  direction: string;
  text: string;
  created_at: string;
  // docs/ROADMAP.md §3.1 -- "internal" rows are escalation notes, visible
  // only to the business owner, never sent to the customer.
  audience: string;
  escalation_id: string | null;
  diagnostics?: MessageDiagnostics | null;
}

export interface Escalation {
  id: string;
  conversation_id: string;
  reason: string;
  layer: string;
  status: string;
  created_at: string;
  channel_type: string;
  is_test: boolean;
}

export interface ConversationPanelContextValue {
  isOpen: boolean;
  activeChannelType: string | null;
  openPanel: (channelType: string) => void;
  closePanel: () => void;

  conversations: Conversation[] | null;
  conversationsError: string | null;

  // Pending escalations keyed by conversation_id -- a conversation shows up
  // here only while it has an unresolved escalation (docs/ARCHITECTURE.md
  // §5), which is also what the panel's "escalated only" filter reads from.
  escalationByConversationId: Map<string, Escalation>;
  // Every escalation regardless of status, keyed by its own id -- what the
  // internal-note bubble (docs/ROADMAP.md §3.1) uses to decide whether to
  // still show a Resolve action on a given note (escalationByConversationId
  // above only ever holds pending ones, and only one per conversation).
  escalationById: Map<string, Escalation>;
  // ChannelRail's per-icon badge -- one count per channel_type, not a
  // single tenant-wide number, now that Test Console channels mean more
  // than one channel type can be live at once.
  pendingEscalationCountByChannelType: Record<string, number>;

  activeFilter: ConversationFilterKey | null;
  toggleFilter: (key: ConversationFilterKey) => void;

  selectedConversationId: string | null;
  selectConversation: (id: string) => void;
  backToList: () => void;

  messages: Message[] | null;
  threadError: string | null;

  resolveEscalation: (escalationId: string) => Promise<void>;
  resolvingEscalationId: string | null;
  resolveError: string | null;
}

export const ConversationPanelContext = createContext<ConversationPanelContextValue | null>(
  null,
);
