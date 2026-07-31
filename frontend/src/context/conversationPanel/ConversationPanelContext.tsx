import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import { debounce } from "../../utils/debounce";
import { ConversationPanelContext } from "./context";
import type { Conversation, ConversationFilterKey, Escalation, Message } from "./context";

interface _LiveUpdateEvent {
  type?: string;
  channel_type?: string;
  conversation_id?: string;
  reason?: string;
}

// A burst of SSE events (several messages in quick succession) should
// trigger one refetch, not one per event -- same reasoning and delay as
// iotops-workspace's own EventsContext.tsx debounces its SSE-triggered
// refetches.
const _REFETCH_DEBOUNCE_MS = 400;

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

  // Exclusive, not a Set -- clicking a chip cancels out whatever was
  // active before, rather than broadening the list to an OR of several
  // (direct instruction, reversing the multi-select first pass).
  const [activeFilter, setActiveFilter] = useState<ConversationFilterKey | null>(null);
  const toggleFilter = useCallback((key: ConversationFilterKey) => {
    setActiveFilter((current) => (current === key ? null : key));
  }, []);

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

  // Every escalation regardless of status, keyed by id -- MessageThread's
  // internal-note bubbles (docs/ROADMAP.md §3.1) need this to tell a still-
  // pending note (show Resolve) from an already-resolved one (audit trail
  // only), which escalationByConversationId above can't answer (it only
  // ever holds pending rows).
  const escalationById = useMemo(() => {
    const map = new Map<string, Escalation>();
    for (const escalation of escalations) {
      map.set(escalation.id, escalation);
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
      // "resume where I left off." Same reasoning extends to the rail
      // filter chips: a filter active on one platform (e.g. "Hot lead")
      // silently carrying over and hiding rows on the *next* platform
      // you open would look like a bug, not a feature -- each platform
      // starts unfiltered.
      setSelectedConversationId(null);
      setMessages(null);
      setThreadError(null);
      setActiveFilter(null);
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

  // Debounced so a burst of SSE events (several messages in quick
  // succession) triggers one refetch, not one per event -- same reasoning
  // as iotops-workspace's own EventsContext.tsx. Each reads latestRef
  // fresh at call time rather than closing over the function passed to
  // debounce() at creation time, since useRef's initializer only runs
  // once and these need whatever loadConversations/etc. currently is.
  const debouncedLoadEscalations = useRef(
    debounce(() => {
      void latestRef.current.loadEscalations();
    }, _REFETCH_DEBOUNCE_MS),
  ).current;

  const debouncedLoadConversations = useRef(
    debounce((channelType: string) => {
      void latestRef.current.loadConversations(channelType);
    }, _REFETCH_DEBOUNCE_MS),
  ).current;

  const debouncedSelectConversation = useRef(
    debounce((conversationId: string) => {
      latestRef.current.selectConversation(conversationId);
    }, _REFETCH_DEBOUNCE_MS),
  ).current;

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
          debouncedLoadConversations(current.activeChannelType);
        }
        if (
          current.selectedConversationId !== null &&
          data.conversation_id === current.selectedConversationId
        ) {
          debouncedSelectConversation(current.selectedConversationId);
        }
      } else if (data.type === "escalation") {
        // Ground-truth refetch (full GET /escalations, replacing
        // `escalations` wholesale), not a client-side +1 patch on the
        // badge counts -- iotops-workspace tried the increment-on-event
        // approach for its own ActivityBar badges first and abandoned it:
        // a live count nudged by every individual event doesn't stay
        // truthful (an event doesn't map 1:1 to "the badge should go up
        // by exactly one" -- resolutions, dedup, and reconnect gaps all
        // break that assumption). `pendingEscalationCountByChannelType`/
        // `escalationByConversationId` below are both plain useMemos over
        // whatever `escalations` currently holds, so a full refetch here
        // is the only place this count is ever produced -- there is no
        // increment path to accidentally reintroduce.
        debouncedLoadEscalations();
      }
    });

    // Reconnect-refetch: closes the Redis pub/sub no-buffering gap -- a
    // message published while nobody was subscribed is simply gone, so
    // this is the only way to catch back up after a reconnect (onopen
    // fires on every reconnect, including the browser's own automatic
    // retry, plus the initial connect). Matches iotops-workspace's own
    // EventsContext.tsx, which hit this exact gap first -- its own
    // comment on this same fix is the reason it's here from the start
    // rather than needing to be rediscovered. Not debounced (unlike the
    // per-event refetches above) -- onopen fires rarely, there's no burst
    // to protect against here.
    source.onopen = () => {
      const current = latestRef.current;
      void current.loadEscalations();
      if (current.activeChannelType !== null) {
        void current.loadConversations(current.activeChannelType);
      }
      if (current.selectedConversationId !== null) {
        current.selectConversation(current.selectedConversationId);
      }
    };

    // Known, accepted limitation (docs/ROADMAP.md §3.5): EventSource
    // auto-reconnects on a dropped connection, but if the JWT expires
    // mid-session the stream will 401 and keep silently retrying until the
    // user logs in again -- not a real concern at Phase 1's session
    // lengths (jwt_expires_minutes defaults to 24h).
    return () => source.close();
    // debouncedLoad*/debouncedSelectConversation are referentially stable
    // across renders (each created once via useRef(...).current), so
    // listing them here doesn't cause any extra reconnects -- it's just
    // what satisfies the hook's own dependency check honestly, same
    // effect as iotops-workspace's EventsContext.tsx suppressing this
    // exact warning for the same reason (there, via an inline disable
    // comment instead).
  }, [token, debouncedLoadConversations, debouncedLoadEscalations, debouncedSelectConversation]);

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
      escalationById,
      pendingEscalationCountByChannelType,
      activeFilter,
      toggleFilter,
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
      escalationById,
      pendingEscalationCountByChannelType,
      activeFilter,
      toggleFilter,
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
