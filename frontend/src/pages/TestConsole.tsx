import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { MessageThread } from "../components/MessageThread";
import { RefreshIcon } from "../components/icons";
import type { Message } from "../context/conversationPanel/context";
import "./TestConsole.css";

const PLATFORMS = ["telegram", "whatsapp", "instagram", "facebook", "email"] as const;

interface TestConversationResponse {
  conversation_id: string | null;
  messages: Message[];
}

interface SendTestMessageResponse {
  conversation_id: string;
  messages: Message[];
  escalated: boolean;
  escalation_reason: string | null;
}

// A fresh id per test "session" (crypto.randomUUID(), first 8 chars is
// plenty unique for casual manual testing) -- this is what becomes
// Conversation.external_contact_id for a test conversation. A new session
// means a brand-new Conversation row rather than continuing whatever was
// last sent on this platform, so multiple test runs stay independently
// trackable in ChannelRail/ConversationPanel (which is unaffected --
// real/other test conversations there stay fully persistent regardless).
function generateSessionId(): string {
  return `test-${crypto.randomUUID().slice(0, 8)}`;
}

export default function TestConsole() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();

  const [channelType, setChannelType] = useState<(typeof PLATFORMS)[number]>("telegram");
  // Not persisted anywhere (no localStorage/sessionStorage) -- navigating
  // away and back, or a page reload, already starts a new session for
  // free via a fresh mount; the New Session button below is for resetting
  // without leaving the page.
  const [sessionId, setSessionId] = useState(generateSessionId);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [escalatedNotice, setEscalatedNotice] = useState<string | null>(null);

  const [inputText, setInputText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const loadConversation = useCallback(
    async (platform: string, contactId: string) => {
      setLoadError(null);
      setEscalatedNotice(null);
      setMessages(null);
      try {
        const result = await apiGet<TestConversationResponse>(
          `/test/conversations?channel_type=${encodeURIComponent(platform)}` +
            `&external_contact_id=${encodeURIComponent(contactId)}`,
          token,
        );
        setMessages(result.messages);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
          return;
        }
        setLoadError(t("testConsole.loadError"));
      }
    },
    [token, logout, t],
  );

  useEffect(() => {
    void loadConversation(channelType, sessionId);
  }, [channelType, sessionId, loadConversation]);

  function handleNewSession() {
    setSessionId(generateSessionId());
    setInputText("");
    setSendError(null);
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const stripped = inputText.trim();
    if (!stripped || sending) return;

    setSendError(null);
    setSending(true);
    try {
      const result = await apiPost<SendTestMessageResponse>(
        "/test/conversations/messages",
        { channel_type: channelType, external_contact_id: sessionId, text: stripped },
        token,
      );
      setMessages(result.messages);
      setEscalatedNotice(result.escalated ? result.escalation_reason : null);
      setInputText("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSendError(t("testConsole.sendError"));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.testConsole")}</h1>
      </div>
      <p className="page__description">{t("pages.testConsole")}</p>

      <div className="test-console__toolbar">
        <label className="form__field test-console__platform">
          {t("testConsole.platform")}
          <select
            value={channelType}
            onChange={(event) =>
              setChannelType(event.target.value as (typeof PLATFORMS)[number])
            }
          >
            {PLATFORMS.map((platform) => (
              <option key={platform} value={platform}>
                {t(`channelRail.${platform}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="button test-console__new-session"
          onClick={handleNewSession}
          title={t("testConsole.newSessionHint")}
        >
          <RefreshIcon />
          {t("testConsole.newSession")}
        </button>
      </div>
      <p className="test-console__session-label">
        {t("testConsole.sessionLabel", { sessionId })}
      </p>

      <div className="card test-console__thread-card">
        {loadError && (
          <p className="error-message" role="alert">
            {loadError}
          </p>
        )}
        {messages === null && !loadError && (
          <p className="test-console__hint">{t("testConsole.loading")}</p>
        )}
        {messages !== null && messages.length === 0 && (
          <p className="test-console__hint">{t("testConsole.empty")}</p>
        )}
        {messages !== null && messages.length > 0 && (
          <div className="test-console__thread">
            <MessageThread messages={messages} />
          </div>
        )}
        {escalatedNotice !== null && (
          <p className="test-console__escalated-notice">
            {t("testConsole.escalatedNotice", { reason: escalatedNotice })}
          </p>
        )}
      </div>

      <form className="test-console__input-row" onSubmit={(event) => void handleSend(event)}>
        <input
          type="text"
          className="test-console__input"
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          placeholder={t("testConsole.inputPlaceholder")}
          disabled={sending}
        />
        <button
          type="submit"
          className="button button--primary"
          disabled={sending || inputText.trim() === ""}
        >
          {sending ? t("testConsole.sending") : t("testConsole.send")}
        </button>
      </form>
      {sendError && (
        <p className="error-message" role="alert">
          {sendError}
        </p>
      )}
    </section>
  );
}
