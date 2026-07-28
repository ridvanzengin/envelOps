import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { MessageThread } from "../components/MessageThread";
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

export default function TestConsole() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();

  const [channelType, setChannelType] = useState<(typeof PLATFORMS)[number]>("telegram");
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [escalatedNotice, setEscalatedNotice] = useState<string | null>(null);

  const [inputText, setInputText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const loadConversation = useCallback(
    async (platform: string) => {
      setLoadError(null);
      setEscalatedNotice(null);
      setMessages(null);
      try {
        const result = await apiGet<TestConversationResponse>(
          `/test/conversations?channel_type=${encodeURIComponent(platform)}`,
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
    void loadConversation(channelType);
  }, [channelType, loadConversation]);

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const stripped = inputText.trim();
    if (!stripped || sending) return;

    setSendError(null);
    setSending(true);
    try {
      const result = await apiPost<SendTestMessageResponse>(
        "/test/conversations/messages",
        { channel_type: channelType, text: stripped },
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

      <label className="form__field test-console__platform">
        {t("testConsole.platform")}
        <select
          value={channelType}
          onChange={(event) => setChannelType(event.target.value as (typeof PLATFORMS)[number])}
        >
          {PLATFORMS.map((platform) => (
            <option key={platform} value={platform}>
              {t(`channelRail.${platform}`)}
            </option>
          ))}
        </select>
      </label>

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
