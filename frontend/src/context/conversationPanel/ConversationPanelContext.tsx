import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import { ConversationPanelContext } from "./context";
import type { Conversation, Escalation, Message } from "./context";

export function ConversationPanelProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { token, logout } = useAuth();

  const [isOpen, setIsOpen] = useState(false);
  const [activeChannelType, setActiveChannelType] = useState<string | null>(null);

  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [conversationsError, setConversationsError] = useState<string | null>(null);

  // Fetched once on mount (not just on openPanel) -- ChannelRail's
  // escalation badges must show a count even while the panel itself is
  // closed, and this is the only source those counts can come from (no
  // backend change: derived client-side from GET /escalations, same as
  // the old standalone Escalation queue page did).
  const [escalations, setEscalations] = useState<Escalation[]>([]);

  const [escalatedOnly, setEscalatedOnly] = useState(false);

  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [threadError, setThreadError] = useState<string | null>(null);

  const [resolvingEscalationId, setResolvingEscalationId] = useState<string | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const loadEscalations = useCallback(async () => {
    try {
      const result = await apiGet<Escalation[]>("/escalations", token);
      setEscalations(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
      }
      // Silently leaves the previous counts in place -- this is a
      // secondary, badge-only signal, not a page with its own error UI.
    }
  }, [token, logout]);

  useEffect(() => {
    void loadEscalations();
  }, [loadEscalations]);

  const escalationByConversationId = useMemo(() => {
    const map = new Map<string, Escalation>();
    for (const escalation of escalations) {
      if (escalation.status === "pending") {
        map.set(escalation.conversation_id, escalation);
      }
    }
    return map;
  }, [escalations]);

  const pendingEscalationCountByChannelType = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const escalation of escalations) {
      if (escalation.status === "pending") {
        counts[escalation.channel_type] = (counts[escalation.channel_type] ?? 0) + 1;
      }
    }
    return counts;
  }, [escalations]);

  const loadConversations = useCallback(
    async (channelType: string) => {
      setConversationsError(null);
      try {
        const result = await apiGet<Conversation[]>(
          `/conversations?channel_type=${encodeURIComponent(channelType)}`,
          token,
        );
        setConversations(result);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setConversationsError(t("conversationPanel.loadError"));
      }
    },
    [token, logout, t],
  );

  const openPanel = useCallback(
    (channelType: string) => {
      setIsOpen(true);
      setActiveChannelType(channelType);
      // Always lands on the list, never a remembered thread -- clicking a
      // channel icon means "show me this channel's conversations," not
      // "resume where I left off."
      setSelectedConversationId(null);
      setMessages(null);
      setThreadError(null);
      void loadConversations(channelType);
      void loadEscalations();
    },
    [loadConversations, loadEscalations],
  );

  const closePanel = useCallback(() => {
    setIsOpen(false);
  }, []);

  const selectConversation = useCallback(
    (id: string) => {
      setSelectedConversationId(id);
      setThreadError(null);
      setMessages(null);
      apiGet<Message[]>(`/conversations/${id}/messages`, token)
        .then(setMessages)
        .catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 401) {
            logout();
            return;
          }
          setThreadError(t("conversationPanel.threadLoadError"));
        });
    },
    [token, logout, t],
  );

  const backToList = useCallback(() => {
    setSelectedConversationId(null);
    setMessages(null);
    setThreadError(null);
  }, []);

  const resolveEscalation = useCallback(
    async (escalationId: string) => {
      setResolveError(null);
      setResolvingEscalationId(escalationId);
      try {
        const updated = await apiPost<Escalation>(
          `/escalations/${escalationId}/resolve`,
          undefined,
          token,
        );
        setEscalations((current) =>
          current.map((row) => (row.id === escalationId ? updated : row)),
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setResolveError(t("escalations.resolveError"));
      } finally {
        setResolvingEscalationId(null);
      }
    },
    [token, logout, t],
  );

  const value = useMemo(
    () => ({
      isOpen,
      activeChannelType,
      openPanel,
      closePanel,
      conversations,
      conversationsError,
      escalationByConversationId,
      pendingEscalationCountByChannelType,
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
    }),
    [
      isOpen,
      activeChannelType,
      openPanel,
      closePanel,
      conversations,
      conversationsError,
      escalationByConversationId,
      pendingEscalationCountByChannelType,
      escalatedOnly,
      selectedConversationId,
      selectConversation,
      backToList,
      messages,
      threadError,
      resolveEscalation,
      resolvingEscalationId,
      resolveError,
    ],
  );

  return (
    <ConversationPanelContext.Provider value={value}>
      {children}
    </ConversationPanelContext.Provider>
  );
}
