import { createContext } from "react";

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

// One entry per live "escalation" SSE event (docs/ROADMAP.md §3.5) --
// deliberately a client-only, ephemeral notification, not a projection of
// the Escalation row itself (which ChannelRail's badges already read from
// `escalations` above via a full GET /escalations refetch on the same
// event). `receivedAt` drives ActivityBar's relative-time display.
export interface LiveEscalationNotification {
  conversationId: string;
  channelType: string;
  reason: string;
  receivedAt: number;
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
  // ChannelRail's per-icon badge -- one count per channel_type, not a
  // single tenant-wide number, now that Test Console channels mean more
  // than one channel type can be live at once.
  pendingEscalationCountByChannelType: Record<string, number>;

  escalatedOnly: boolean;
  setEscalatedOnly: (value: boolean) => void;

  selectedConversationId: string | null;
  selectConversation: (id: string) => void;
  backToList: () => void;

  messages: Message[] | null;
  threadError: string | null;

  resolveEscalation: (escalationId: string) => Promise<void>;
  resolvingEscalationId: string | null;
  resolveError: string | null;

  // docs/ROADMAP.md §3.5 -- ActivityBar's own notification list, capped to
  // the most recent few, newest first.
  liveEscalationNotifications: LiveEscalationNotification[];
  dismissNotification: (conversationId: string) => void;
}

export const ConversationPanelContext = createContext<ConversationPanelContextValue | null>(
  null,
);
