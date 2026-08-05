import { useCallback, useEffect, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { MessageThread } from "../components/MessageThread";
import { RefreshIcon } from "../components/icons";
import type { Message } from "../context/conversationPanel/context";
import { CHANNEL_TYPES as PLATFORMS } from "../lib/channels";
import { handleTextareaEnterKey } from "../utils/submitOnEnter";
import "./TestConsole.css";

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
  // Editable copy of sessionId, committed on blur/Enter rather than on
  // every keystroke -- sessionId IS Conversation.external_contact_id
  // (used directly in loadConversation's effect below), so updating it
  // per-character would fire a GET on every keystroke and look like the
  // session kept switching out from under whatever was just typed. There
  // is no rename endpoint (nor should there be one -- external_contact_id
  // is how a conversation is identified, not a cosmetic label), so
  // committing a new name doesn't rename the current session's thread, it
  // switches to (or creates, if new) a *different* session under that
  // name -- the same thing typing a different id here has always done,
  // just user-chosen instead of only ever auto-generated.
  const [sessionNameDraft, setSessionNameDraft] = useState(sessionId);
  useEffect(() => {
    setSessionNameDraft(sessionId);
  }, [sessionId]);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [escalatedNotice, setEscalatedNotice] = useState<string | null>(null);

  const [inputText, setInputText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // The inbound text already submitted to the backend but not yet folded
  // into `messages` -- shown immediately on submit (optimistic send)
  // instead of waiting for the full pipeline round-trip to complete.
  // Deliberately NOT cleared on a failed send: in the real (non-demo) path
  // the inbound message is committed before the pipeline runs (see
  // app/test_console/api.py), so it's already durably saved even when the
  // AI reply itself fails -- clearing it here would hide a message that
  // genuinely was sent.
  const [pendingInbound, setPendingInbound] = useState<string | null>(null);

  const loadConversation = useCallback(
    async (platform: string, contactId: string) => {
      setLoadError(null);
      setEscalatedNotice(null);
      setMessages(null);
      setPendingInbound(null);
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
    setPendingInbound(null);
  }

  function commitSessionName() {
    const trimmed = sessionNameDraft.trim();
    // Blank isn't a valid session identifier -- revert rather than send
    // an empty external_contact_id.
    if (trimmed === "") {
      setSessionNameDraft(sessionId);
      return;
    }
    if (trimmed !== sessionId) {
      setSessionId(trimmed);
    }
  }

  function handleSessionNameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.currentTarget.blur();
    } else if (event.key === "Escape") {
      setSessionNameDraft(sessionId);
      event.currentTarget.blur();
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const stripped = inputText.trim();
    if (!stripped || sending) return;

    // Optimistic send: the message shows immediately and the input clears
    // right away, rather than waiting for the full pipeline round-trip
    // (up to 4 sequential Gemini calls, CLAUDE.md) before either happens.
    // `sending` still gates the Send button/input against a second submit
    // on the same session -- concurrent runs against the same LangGraph
    // thread_id are a real, documented gotcha (CLAUDE.md), not just a UX
    // nicety -- but the button's own label no longer changes to "Sending...";
    // the inline Thinking indicator below is what communicates progress now.
    setSendError(null);
    setInputText("");
    setPendingInbound(stripped);
    setSending(true);
    try {
      const result = await apiPost<SendTestMessageResponse>(
        "/test/conversations/messages",
        { channel_type: channelType, external_contact_id: sessionId, text: stripped },
        token,
      );
      setMessages(result.messages);
      setEscalatedNotice(result.escalated ? result.escalation_reason : null);
      setPendingInbound(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      // ApiError's own message is the backend's HTTPException detail --
      // for an AI provider failure that's already the friendly, non-leaking
      // text app/main.py's exception handler produces (see AiProviderError),
      // not a raw Gemini error. Only a genuine network-level failure (fetch
      // itself throwing, no response at all) falls back to the generic
      // translated message.
      setSendError(err instanceof ApiError ? err.message : t("testConsole.sendError"));
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
        <label className="form__field test-console__session-name">
          {t("testConsole.sessionName")}
          <input
            type="text"
            value={sessionNameDraft}
            onChange={(event) => setSessionNameDraft(event.target.value)}
            onBlur={commitSessionName}
            onKeyDown={handleSessionNameKeyDown}
            placeholder={t("testConsole.sessionNamePlaceholder")}
          />
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

      <div className="card test-console__thread-card">
        {loadError && (
          <p className="error-message" role="alert">
            {loadError}
          </p>
        )}
        {messages === null && !loadError && (
          <p className="test-console__hint">{t("testConsole.loading")}</p>
        )}
        {messages !== null && messages.length === 0 && pendingInbound === null && (
          <p className="test-console__hint">{t("testConsole.empty")}</p>
        )}
        {messages !== null && (messages.length > 0 || pendingInbound !== null) && (
          <div className="test-console__thread">
            <MessageThread
              messages={messages}
              pendingInbound={pendingInbound}
              thinking={sending}
            />
          </div>
        )}
        {escalatedNotice !== null && (
          <p className="test-console__escalated-notice">
            {t("testConsole.escalatedNotice", { reason: escalatedNotice })}
          </p>
        )}
      </div>

      <form className="test-console__input-row" onSubmit={(event) => void handleSend(event)}>
        <textarea
          className="test-console__input"
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          onKeyDown={(event) => handleTextareaEnterKey(event, setInputText)}
          placeholder={t("testConsole.inputPlaceholder")}
          disabled={sending}
          rows={1}
        />
        <button
          type="submit"
          className="button button--primary"
          disabled={sending || inputText.trim() === ""}
        >
          {t("testConsole.send")}
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
