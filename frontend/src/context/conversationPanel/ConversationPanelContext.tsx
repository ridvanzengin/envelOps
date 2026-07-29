import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import { ConversationPanelContext } from "./context";
import type { Conversation, Escalation, LiveEscalationNotification, Message } from "./context";

// Capped so a quiet moment away from the tab doesn't turn ActivityBar into
// an ever-growing list -- ChannelRail's own badges (pendingEscalationCountByChannelType)
// are still the source of truth for "how many are actually pending," this
// is just a recent-activity feed.
const _MAX_LIVE_NOTIFICATIONS = 5;

interface _LiveUpdateEvent {
  type?: string;
  channel_type?: string;
  conversation_id?: string;
  reason?: string;
}

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

  const [liveEscalationNotifications, setLiveEscalationNotifications] = useState<
    LiveEscalationNotification[]
  >([]);

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

  const dismissNotification = useCallback((conversationId: string) => {
    setLiveEscalationNotifications((current) =>
      current.filter((notification) => notification.conversationId !== conversationId),
    );
  }, []);

  // Read inside the SSE handler below instead of listed as effect deps --
  // the connection itself should only open/close when `token` changes
  // (logging out/in), not reconnect every time the panel's own open
  // channel/conversation changes. Updated on every render (not inside an
  // effect) is the standard way to keep a ref "live" without that forcing
  // extra re-renders or effect re-runs of its own.
  const latestRef = useRef({
    activeChannelType,
    selectedConversationId,
    loadConversations,
    loadEscalations,
    selectConversation,
  });
  latestRef.current = {
    activeChannelType,
    selectedConversationId,
    loadConversations,
    loadEscalations,
    selectConversation,
  };

  useEffect(() => {
    if (token === null) {
      return;
    }
    // EventSource can't set an Authorization header, so the token travels
    // as a query param instead (docs/ROADMAP.md §3.5, app/auth/dependencies.py's
    // get_current_user_from_query) -- the one deliberate exception to this
    // codebase's usual Bearer-header-only auth.
    const source = new EventSource(`/events/stream?token=${encodeURIComponent(token)}`);

    source.addEventListener("update", (event) => {
      let data: _LiveUpdateEvent;
      try {
        data = JSON.parse((event as MessageEvent<string>).data) as _LiveUpdateEvent;
      } catch {
        return;
      }
      const current = latestRef.current;

      if (data.type === "message") {
        if (current.activeChannelType !== null && data.channel_type === current.activeChannelType) {
          void current.loadConversations(current.activeChannelType);
        }
        if (
          current.selectedConversationId !== null &&
          data.conversation_id === current.selectedConversationId
        ) {
          current.selectConversation(current.selectedConversationId);
        }
      } else if (data.type === "escalation") {
        void current.loadEscalations();
        setLiveEscalationNotifications((existing) =>
          [
            {
              conversationId: data.conversation_id ?? "",
              channelType: data.channel_type ?? "",
              reason: data.reason ?? "",
              receivedAt: Date.now(),
            },
            ...existing,
          ].slice(0, _MAX_LIVE_NOTIFICATIONS),
        );
      }
    });

    // Known, accepted limitation (docs/ROADMAP.md §3.5): EventSource
    // auto-reconnects on a dropped connection, but if the JWT expires
    // mid-session the stream will 401 and keep silently retrying until the
    // user logs in again -- not a real concern at Phase 1's session
    // lengths (jwt_expires_minutes defaults to 24h).
    return () => source.close();
  }, [token]);

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
      liveEscalationNotifications,
      dismissNotification,
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
      liveEscalationNotifications,
      dismissNotification,
    ],
  );

  return (
    <ConversationPanelContext.Provider value={value}>
      {children}
    </ConversationPanelContext.Provider>
  );
}
