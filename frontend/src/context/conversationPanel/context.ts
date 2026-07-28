import { createContext } from "react";

export interface Conversation {
  id: string;
  external_contact_id: string;
  status: string;
  last_message_text: string | null;
  last_message_at: string | null;
}

export interface Message {
  id: string;
  direction: string;
  text: string;
  created_at: string;
}

export interface Escalation {
  id: string;
  conversation_id: string;
  reason: string;
  layer: string;
  status: string;
  created_at: string;
}

export interface ConversationPanelContextValue {
  isOpen: boolean;
  openPanel: () => void;
  closePanel: () => void;

  conversations: Conversation[] | null;
  conversationsError: string | null;

  // Pending escalations keyed by conversation_id -- a conversation shows up
  // here only while it has an unresolved escalation (docs/ARCHITECTURE.md
  // §5), which is also what ChannelRail's badge count and the panel's
  // "escalated only" filter both read from.
  escalationByConversationId: Map<string, Escalation>;
  pendingEscalationCount: number;

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
}

export const ConversationPanelContext = createContext<ConversationPanelContextValue | null>(
  null,
);
