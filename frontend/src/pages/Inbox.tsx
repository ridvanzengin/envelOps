import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

interface Conversation {
  id: string;
  external_contact_id: string;
  status: string;
  last_message_text: string | null;
  last_message_at: string | null;
}

interface Message {
  id: string;
  direction: string;
  text: string;
  created_at: string;
}

export default function Inbox() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [threadError, setThreadError] = useState<string | null>(null);

  const loadConversations = useCallback(async () => {
    setListError(null);
    try {
      const result = await apiGet<Conversation[]>("/conversations", token);
      setConversations(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setListError(t("inbox.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    setThreadError(null);
    setMessages(null);
    apiGet<Message[]>(`/conversations/${selectedId}/messages`, token)
      .then(setMessages)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setThreadError(t("inbox.threadLoadError"));
      });
  }, [selectedId, token, logout, t]);

  return (
    <section>
      <h1>{t("nav.inbox")}</h1>
      <p>{t("pages.inbox")}</p>

      {listError && <p role="alert">{listError}</p>}
      {conversations === null && !listError && <p>{t("inbox.loading")}</p>}
      {conversations !== null && conversations.length === 0 && <p>{t("inbox.empty")}</p>}

      {conversations !== null && conversations.length > 0 && (
        <div style={{ display: "flex", gap: "2rem" }}>
          <ul>
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <button type="button" onClick={() => setSelectedId(conversation.id)}>
                  <strong>{conversation.external_contact_id}</strong>
                  <br />
                  {conversation.last_message_text ?? t("inbox.noMessages")}
                </button>
              </li>
            ))}
          </ul>

          <div>
            {selectedId === null && <p>{t("inbox.selectAConversation")}</p>}
            {threadError && <p role="alert">{threadError}</p>}
            {selectedId !== null && messages === null && !threadError && (
              <p>{t("inbox.threadLoading")}</p>
            )}
            {messages !== null && (
              <ul>
                {messages.map((message) => (
                  <li key={message.id}>
                    <strong>{message.direction}</strong>: {message.text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
