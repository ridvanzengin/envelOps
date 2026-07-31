import { useCallback, useEffect, useState } from "react";
import type { ComponentType, FormEvent, SVGProps } from "react";
import { useTranslation } from "react-i18next";

import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import {
  AlertTriangleIcon,
  ArrowUpCircleIcon,
  CreditCardIcon,
  FileTextIcon,
  FlagIcon,
  FlaskIcon,
  GlobeIcon,
  HelpCircleIcon,
  KnowledgeIcon,
  ShieldIcon,
  SmileIcon,
  TargetIcon,
  TrashIcon,
} from "../components/icons";
import { CHANNEL_TYPES } from "../lib/channels";
import { handleTextareaEnterKey } from "../utils/submitOnEnter";

interface TriggerPhrase {
  id: string;
  phrase: string;
}

// System defaults (docs/ARCHITECTURE.md §5) are compiled regex in
// app/escalation/safety_gate.py, not DB rows -- there's nothing to fetch
// for them, so these three category labels are static, translated copy
// mirroring safety_gate.py's own three checks. Shown locked: no edit, no
// delete, ever, by design.
const SYSTEM_DEFAULT_CATEGORY_KEYS = [
  "contraindication",
  "symptom",
  "outcomeGuarantee",
] as const;

// Mirrors backend/app/tenants/behavior_config.py exactly -- one combined
// shape for the full GET response; PATCH sends only one tab's own slice
// at a time (see LEFT_TAB_ORDER/RIGHT_TAB_ORDER/buildTabPatch below),
// never this whole object.
type BusinessTone = "friendly_business" | "formal_business";
type ClosingAction = "keep_chatting" | "escalate_to_human" | "book_or_checkout";

interface BehaviorAreaBase {
  additional_context: string | null;
}

interface GreetingConfig extends BehaviorAreaBase {
  tone: BusinessTone;
  invite_followup_question: boolean;
}

interface OffTopicConfig extends BehaviorAreaBase {
  tone: BusinessTone;
}

interface KnowledgeQueryConfig extends BehaviorAreaBase {
  tone: BusinessTone;
  not_found_max_distance: number | null;
}

interface ComplaintConfig extends BehaviorAreaBase {
  empathetic_acknowledgment: boolean;
}

interface LeadHandlingConfig extends BehaviorAreaBase {
  closing_action_override: ClosingAction | null;
  hot_lead_requires_purchase_intent: boolean;
}

interface EscalationCoverConfig extends BehaviorAreaBase {
  tone: BusinessTone;
}

interface BookOrCheckoutConfig extends BehaviorAreaBase {
  cta_style: "natural_mention" | "direct_cta";
}

interface ToolCallingConfig extends BehaviorAreaBase {
  order_status_lookup_enabled: boolean;
  inventory_check_enabled: boolean;
}

interface ChannelToneConfig {
  formality: "casual_chat" | "formal_email";
  include_greeting: boolean;
  include_sign_off: boolean;
  length_guidance: "brief" | "as_needed";
}

interface TenantBehaviorConfig {
  schema_version: number;
  greeting: GreetingConfig;
  off_topic: OffTopicConfig;
  knowledge_query: KnowledgeQueryConfig;
  complaint: ComplaintConfig;
  lead_handling: LeadHandlingConfig;
  escalation_cover: EscalationCoverConfig;
  book_or_checkout: BookOrCheckoutConfig;
  tool_calling: ToolCallingConfig;
  channel_overrides: Record<string, ChannelToneConfig>;
  general_context: string | null;
}

interface TenantSettings {
  closing_action: ClosingAction;
  closing_link: string | null;
  behavior_config: TenantBehaviorConfig;
}

type BehaviorAreaKey =
  | "greeting"
  | "off_topic"
  | "knowledge_query"
  | "complaint"
  | "lead_handling"
  | "escalation_cover"
  | "book_or_checkout"
  | "tool_calling";

// One entry per tab -- each of the first 11 saves independently, PATCHing
// only its own slice of TenantSettings (buildTabPatch below); "safety" is
// the odd one out (moved in from its own always-visible column, docs/
// ROADMAP.md UI polish pass) -- it has its own separate add/delete
// endpoints (handleSubmit/handleDelete below), not a PATCH slice, so it's
// excluded from buildTabPatch's switch entirely. Order here is tab order.
type TabKey =
  | "closing"
  | "greeting"
  | "offTopic"
  | "knowledgeQuery"
  | "complaint"
  | "leadHandling"
  | "escalationCover"
  | "bookOrCheckout"
  | "toolCalling"
  | "channels"
  | "generalContext"
  | "safety";

// Split into two independent tab groups, each with its own nav row and
// its own card below it (direct instruction) -- two visible cards at
// once, not one shared active tab, so e.g. Closing behavior and Safety
// trigger phrases can both be on screen together. 6 + 6 (all 12 tabs
// accounted for); grouped left = conversation-facing tone/behavior
// areas, right = business mechanics + safety.
const LEFT_TAB_ORDER: TabKey[] = [
  "greeting",
  "closing",
  "offTopic",
  "knowledgeQuery",
  "complaint",
  "leadHandling",
];

const RIGHT_TAB_ORDER: TabKey[] = [
  "escalationCover",
  "bookOrCheckout",
  "toolCalling",
  "channels",
  "generalContext",
  "safety",
];

const TAB_TITLE_KEYS: Record<TabKey, string> = {
  closing: "settings.tenantSettings.closingBehavior.title",
  greeting: "settings.tenantSettings.greeting.title",
  offTopic: "settings.tenantSettings.offTopic.title",
  knowledgeQuery: "settings.tenantSettings.knowledgeQuery.title",
  complaint: "settings.tenantSettings.complaint.title",
  leadHandling: "settings.tenantSettings.leadHandling.title",
  escalationCover: "settings.tenantSettings.escalationCover.title",
  bookOrCheckout: "settings.tenantSettings.bookOrCheckout.title",
  toolCalling: "settings.tenantSettings.toolCalling.title",
  channels: "settings.tenantSettings.channelOverrides.title",
  generalContext: "settings.tenantSettings.generalContext.title",
  safety: "settings.safetyTriggersTitle",
};

// Card header description shown under each tab's title (docs/ROADMAP.md
// UI polish pass) -- new copy, one per tab, no prior equivalent existed
// since tab content previously had no card/header at all.
const TAB_DESCRIPTION_KEYS: Record<TabKey, string> = {
  closing: "settings.tenantSettings.closingBehavior.description",
  greeting: "settings.tenantSettings.greeting.description",
  offTopic: "settings.tenantSettings.offTopic.description",
  knowledgeQuery: "settings.tenantSettings.knowledgeQuery.description",
  complaint: "settings.tenantSettings.complaint.description",
  leadHandling: "settings.tenantSettings.leadHandling.description",
  escalationCover: "settings.tenantSettings.escalationCover.description",
  bookOrCheckout: "settings.tenantSettings.bookOrCheckout.description",
  toolCalling: "settings.tenantSettings.toolCalling.description",
  channels: "settings.tenantSettings.channelOverrides.description",
  generalContext: "settings.tenantSettings.generalContext.description",
  safety: "settings.safetyDescription",
};

const TAB_ICONS: Record<TabKey, ComponentType<SVGProps<SVGSVGElement>>> = {
  closing: FlagIcon,
  greeting: SmileIcon,
  offTopic: HelpCircleIcon,
  knowledgeQuery: KnowledgeIcon,
  complaint: AlertTriangleIcon,
  leadHandling: TargetIcon,
  escalationCover: ArrowUpCircleIcon,
  bookOrCheckout: CreditCardIcon,
  toolCalling: FlaskIcon,
  channels: GlobeIcon,
  generalContext: FileTextIcon,
  safety: ShieldIcon,
};

// Exactly what PATCH /tenants/settings accepts for a given tab -- always
// that tab's own field(s) in full, never a deeper partial within one
// (app/tenants/api.py's TenantSettingsPatch mirrors this one-slice-per-
// key shape exactly).
function buildTabPatch(tab: TabKey, settings: TenantSettings): Record<string, unknown> {
  switch (tab) {
    case "closing":
      return { closing_action: settings.closing_action, closing_link: settings.closing_link };
    case "greeting":
      return { greeting: settings.behavior_config.greeting };
    case "offTopic":
      return { off_topic: settings.behavior_config.off_topic };
    case "knowledgeQuery":
      return { knowledge_query: settings.behavior_config.knowledge_query };
    case "complaint":
      return { complaint: settings.behavior_config.complaint };
    case "leadHandling":
      return { lead_handling: settings.behavior_config.lead_handling };
    case "escalationCover":
      return { escalation_cover: settings.behavior_config.escalation_cover };
    case "bookOrCheckout":
      return { book_or_checkout: settings.behavior_config.book_or_checkout };
    case "toolCalling":
      return { tool_calling: settings.behavior_config.tool_calling };
    case "channels":
      return { channel_overrides: settings.behavior_config.channel_overrides };
    case "generalContext":
      return { general_context: settings.behavior_config.general_context };
    case "safety":
      // Never actually reachable -- the safety tab renders its own
      // add-phrase form (handleSubmit) instead of the tenant-settings
      // form this function backs, so handleSaveTab/buildTabPatch are
      // never invoked with tab="safety" in practice. Only here to keep
      // this switch exhaustive over TabKey; an empty patch is a safe,
      // inert fallback if that assumption is ever wrong.
      return {};
  }
}

const DEFAULT_CHANNEL_OVERRIDE: ChannelToneConfig = {
  formality: "casual_chat",
  include_greeting: false,
  include_sign_off: false,
  length_guidance: "brief",
};

function ToneSelect({
  value,
  onChange,
  label,
}: {
  value: BusinessTone;
  onChange: (value: BusinessTone) => void;
  label: string;
}) {
  const { t } = useTranslation();
  return (
    <label className="form__field">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value as BusinessTone)}>
        <option value="friendly_business">
          {t("settings.tenantSettings.toneOptions.friendlyBusiness")}
        </option>
        <option value="formal_business">
          {t("settings.tenantSettings.toneOptions.formalBusiness")}
        </option>
      </select>
    </label>
  );
}

function AdditionalContextField({
  value,
  onChange,
  label,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  label: string;
}) {
  return (
    <label className="form__field tenant-settings__fields--full">
      {label}
      <textarea
        maxLength={500}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        onKeyDown={(e) => handleTextareaEnterKey(e, (v) => onChange(v || null))}
        rows={1}
      />
    </label>
  );
}

export default function Settings() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();
  const [phrases, setPhrases] = useState<TriggerPhrase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newPhrase, setNewPhrase] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  // Two independent active tabs, one per column (see LEFT_TAB_ORDER/
  // RIGHT_TAB_ORDER above) -- each defaults to its own group's first tab.
  const [activeLeftTab, setActiveLeftTab] = useState<TabKey>(LEFT_TAB_ORDER[0]);
  const [activeRightTab, setActiveRightTab] = useState<TabKey>(RIGHT_TAB_ORDER[0]);
  // Keyed by tab, not a single shared value -- each tab saves
  // independently, so an in-flight save or a stale error on one tab
  // must never bleed into another tab's button/message. Shared across
  // both columns (a TabKey only ever lives in one column at a time, per
  // LEFT_TAB_ORDER/RIGHT_TAB_ORDER being disjoint), so no per-column
  // duplication needed here.
  const [savingTab, setSavingTab] = useState<TabKey | null>(null);
  const [saveErrors, setSaveErrors] = useState<Partial<Record<TabKey, string>>>({});

  const loadSettings = useCallback(async () => {
    setSettingsError(null);
    try {
      const result = await apiGet<TenantSettings>("/tenants/settings", token);
      setSettings(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSettingsError(t("settings.tenantSettings.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  async function handleSaveTab(tab: TabKey, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) return;
    setSaveErrors((current) => ({ ...current, [tab]: undefined }));
    setSavingTab(tab);
    try {
      const updated = await apiPatch<TenantSettings>(
        "/tenants/settings",
        buildTabPatch(tab, settings),
        token,
      );
      setSettings(updated);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSaveErrors((current) => ({
        ...current,
        [tab]: err instanceof ApiError ? err.message : t("settings.tenantSettings.saveError"),
      }));
    } finally {
      setSavingTab(null);
    }
  }

  function updateClosingAction(value: ClosingAction) {
    setSettings((current) => (current ? { ...current, closing_action: value } : current));
  }

  function updateClosingLink(value: string) {
    setSettings((current) => (current ? { ...current, closing_link: value || null } : current));
  }

  function updateGeneralContext(value: string | null) {
    setSettings((current) =>
      current
        ? { ...current, behavior_config: { ...current.behavior_config, general_context: value } }
        : current,
    );
  }

  function updateArea<K extends BehaviorAreaKey>(
    area: K,
    patch: Partial<TenantBehaviorConfig[K]>,
  ) {
    setSettings((current) =>
      current
        ? {
            ...current,
            behavior_config: {
              ...current.behavior_config,
              [area]: { ...current.behavior_config[area], ...patch },
            },
          }
        : current,
    );
  }

  function toggleChannelOverride(channel: string, enabled: boolean) {
    setSettings((current) => {
      if (!current) return current;
      const overrides = { ...current.behavior_config.channel_overrides };
      if (enabled) {
        overrides[channel] = overrides[channel] ?? DEFAULT_CHANNEL_OVERRIDE;
      } else {
        delete overrides[channel];
      }
      return {
        ...current,
        behavior_config: { ...current.behavior_config, channel_overrides: overrides },
      };
    });
  }

  function updateChannelOverride(channel: string, patch: Partial<ChannelToneConfig>) {
    setSettings((current) => {
      if (!current) return current;
      const existing = current.behavior_config.channel_overrides[channel];
      if (!existing) return current;
      return {
        ...current,
        behavior_config: {
          ...current.behavior_config,
          channel_overrides: {
            ...current.behavior_config.channel_overrides,
            [channel]: { ...existing, ...patch },
          },
        },
      };
    });
  }

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await apiGet<TriggerPhrase[]>(
        "/escalations/trigger-phrases",
        token,
      );
      setPhrases(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(t("settings.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const created = await apiPost<TriggerPhrase>(
        "/escalations/trigger-phrases",
        { phrase: newPhrase },
        token,
      );
      setPhrases((current) => (current ? [...current, created] : [created]));
      setNewPhrase("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setFormError(err instanceof ApiError ? err.message : t("settings.addError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm(t("settings.deleteConfirm"))) return;
    setError(null);
    setDeletingId(id);
    try {
      await apiDelete(`/escalations/trigger-phrases/${id}`, token);
      setPhrases((current) => current?.filter((row) => row.id !== id) ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : t("settings.deleteError"));
    } finally {
      setDeletingId(null);
    }
  }

  // One nav row per column (docs/ROADMAP.md UI polish pass) -- `tabs` is
  // that column's own slice of the 12 (LEFT_TAB_ORDER/RIGHT_TAB_ORDER),
  // `active`/`onSelect` are that column's own independent state, so the
  // two columns' selections never interfere with each other.
  function renderTabNav(tabs: TabKey[], active: TabKey, onSelect: (tab: TabKey) => void) {
    return (
      <div className="tabs" role="tablist">
        {tabs.map((tab) => {
          const TabIcon = TAB_ICONS[tab];
          return (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={active === tab}
              className={`tabs__tab${active === tab ? " tabs__tab--active" : ""}`}
              onClick={() => onSelect(tab)}
            >
              <TabIcon className="tabs__tab-icon" />
              {t(TAB_TITLE_KEYS[tab])}
            </button>
          );
        })}
      </div>
    );
  }

  // The card for whichever tab is active in a given column -- called
  // once per column below with that column's own active tab, so the same
  // icon/title/description/body logic (including the safety-vs-behavior-
  // form branch) doesn't need to exist twice.
  function renderTabCard(tab: TabKey) {
    const TabIcon = TAB_ICONS[tab];
    return (
      <div className="card settings-card">
        <div className="settings-card__header">
          <span className="settings-card__icon">
            <TabIcon />
          </span>
          <div>
            <h2 className="settings-card__title">{t(TAB_TITLE_KEYS[tab])}</h2>
            <p className="settings-card__description">{t(TAB_DESCRIPTION_KEYS[tab])}</p>
          </div>
        </div>

        <div className="settings-card__body">
          {tab === "safety" ? (
              <>
                <h3>{t("settings.systemDefaultsTitle")}</h3>
                <ul className="list">
                  {SYSTEM_DEFAULT_CATEGORY_KEYS.map((key) => (
                    <li key={key} className="list__item">
                      <label>
                        <input type="checkbox" checked disabled />
                        {t(`settings.systemDefaultCategories.${key}`)}
                      </label>
                    </li>
                  ))}
                </ul>

                <h3>{t("settings.tenantPhrasesTitle")}</h3>
                {error && (
                  <p className="error-message" role="alert">
                    {error}
                  </p>
                )}
                {phrases === null && !error && <p>{t("settings.loading")}</p>}
                {phrases !== null && phrases.length === 0 && (
                  <div className="empty-state">{t("settings.empty")}</div>
                )}
                {phrases !== null && phrases.length > 0 && (
                  <ul className="list">
                    {phrases.map((phrase) => (
                      <li key={phrase.id} className="list__item list__item--with-action">
                        <span>{phrase.phrase}</span>
                        <button
                          type="button"
                          className="button button--danger"
                          disabled={deletingId === phrase.id}
                          onClick={() => void handleDelete(phrase.id)}
                          aria-label={t("settings.delete")}
                          title={t("settings.delete")}
                        >
                          <TrashIcon />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <form className="form" onSubmit={(event) => void handleSubmit(event)}>
                  <label className="form__field">
                    {t("settings.newPhrase")}
                    <input
                      type="text"
                      value={newPhrase}
                      onChange={(e) => setNewPhrase(e.target.value)}
                      required
                    />
                  </label>
                  <button
                    type="submit"
                    className="button button--primary button--fit"
                    disabled={submitting}
                  >
                    {submitting ? t("settings.adding") : t("settings.add")}
                  </button>
                  {formError && (
                    <p className="error-message" role="alert">
                      {formError}
                    </p>
                  )}
                </form>
              </>
            ) : (
              <>
                {settingsError && (
                  <p className="error-message" role="alert">
                    {settingsError}
                  </p>
                )}
                {settings === null && !settingsError && (
                  <p>{t("settings.tenantSettings.loading")}</p>
                )}
                {settings !== null && (
                  <form
                    className="form tenant-settings"
                    onSubmit={(event) => void handleSaveTab(tab, event)}
                  >
                    {tab === "closing" && (
                  <div className="tenant-settings__fields">
                    <label className="form__field">
                      {t("settings.tenantSettings.closingBehavior.closingAction")}
                      <select
                        value={settings.closing_action}
                        onChange={(e) => updateClosingAction(e.target.value as ClosingAction)}
                      >
                        <option value="keep_chatting">
                          {t(
                            "settings.tenantSettings.closingBehavior.closingActionOptions.keepChatting",
                          )}
                        </option>
                        <option value="escalate_to_human">
                          {t(
                            "settings.tenantSettings.closingBehavior.closingActionOptions.escalateToHuman",
                          )}
                        </option>
                        <option value="book_or_checkout">
                          {t(
                            "settings.tenantSettings.closingBehavior.closingActionOptions.bookOrCheckout",
                          )}
                        </option>
                      </select>
                    </label>
                    {settings.closing_action === "book_or_checkout" && (
                      <label className="form__field">
                        {t("settings.tenantSettings.closingBehavior.closingLink")}
                        <input
                          type="url"
                          value={settings.closing_link ?? ""}
                          onChange={(e) => updateClosingLink(e.target.value)}
                        />
                      </label>
                    )}
                  </div>
                )}

                {tab === "greeting" && (
                  <div className="tenant-settings__fields">
                    <ToneSelect
                      value={settings.behavior_config.greeting.tone}
                      onChange={(tone) => updateArea("greeting", { tone })}
                      label={t("settings.tenantSettings.tone")}
                    />
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={settings.behavior_config.greeting.invite_followup_question}
                        onChange={(e) =>
                          updateArea("greeting", { invite_followup_question: e.target.checked })
                        }
                      />
                      {t("settings.tenantSettings.greeting.inviteFollowup")}
                    </label>
                    <AdditionalContextField
                      value={settings.behavior_config.greeting.additional_context}
                      onChange={(additional_context) =>
                        updateArea("greeting", { additional_context })
                      }
                      label={t("settings.tenantSettings.greeting.additionalContext")}
                    />
                  </div>
                )}

                {tab === "offTopic" && (
                  <div className="tenant-settings__fields">
                    <ToneSelect
                      value={settings.behavior_config.off_topic.tone}
                      onChange={(tone) => updateArea("off_topic", { tone })}
                      label={t("settings.tenantSettings.tone")}
                    />
                    <AdditionalContextField
                      value={settings.behavior_config.off_topic.additional_context}
                      onChange={(additional_context) =>
                        updateArea("off_topic", { additional_context })
                      }
                      label={t("settings.tenantSettings.offTopic.additionalContext")}
                    />
                  </div>
                )}

                {tab === "knowledgeQuery" && (
                  <div className="tenant-settings__fields">
                    <ToneSelect
                      value={settings.behavior_config.knowledge_query.tone}
                      onChange={(tone) => updateArea("knowledge_query", { tone })}
                      label={t("settings.tenantSettings.tone")}
                    />
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={
                          settings.behavior_config.knowledge_query.not_found_max_distance !== null
                        }
                        onChange={(e) =>
                          updateArea("knowledge_query", {
                            not_found_max_distance: e.target.checked ? 1.0 : null,
                          })
                        }
                      />
                      {t("settings.tenantSettings.knowledgeQuery.limitToConfident")}
                    </label>
                    {settings.behavior_config.knowledge_query.not_found_max_distance !== null && (
                      <label className="form__field tenant-settings__fields--full">
                        {t("settings.tenantSettings.knowledgeQuery.notFoundMaxDistance", {
                          value:
                            settings.behavior_config.knowledge_query.not_found_max_distance.toFixed(
                              1,
                            ),
                        })}
                        <input
                          type="range"
                          min={0}
                          max={2}
                          step={0.1}
                          value={settings.behavior_config.knowledge_query.not_found_max_distance}
                          onChange={(e) =>
                            updateArea("knowledge_query", {
                              not_found_max_distance: Number(e.target.value),
                            })
                          }
                        />
                      </label>
                    )}
                    <AdditionalContextField
                      value={settings.behavior_config.knowledge_query.additional_context}
                      onChange={(additional_context) =>
                        updateArea("knowledge_query", { additional_context })
                      }
                      label={t("settings.tenantSettings.knowledgeQuery.additionalContext")}
                    />
                  </div>
                )}

                {tab === "complaint" && (
                  <div className="tenant-settings__fields">
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={settings.behavior_config.complaint.empathetic_acknowledgment}
                        onChange={(e) =>
                          updateArea("complaint", { empathetic_acknowledgment: e.target.checked })
                        }
                      />
                      {t("settings.tenantSettings.complaint.empatheticAcknowledgment")}
                    </label>
                    <AdditionalContextField
                      value={settings.behavior_config.complaint.additional_context}
                      onChange={(additional_context) =>
                        updateArea("complaint", { additional_context })
                      }
                      label={t("settings.tenantSettings.complaint.additionalContext")}
                    />
                  </div>
                )}

                {tab === "leadHandling" && (
                  <div className="tenant-settings__fields">
                    <label className="form__field">
                      {t("settings.tenantSettings.leadHandling.closingActionOverride")}
                      <select
                        value={settings.behavior_config.lead_handling.closing_action_override ?? ""}
                        onChange={(e) =>
                          updateArea("lead_handling", {
                            closing_action_override: (e.target.value || null) as
                              | ClosingAction
                              | null,
                          })
                        }
                      >
                        <option value="">
                          {t(
                            "settings.tenantSettings.leadHandling.closingActionOverrideOptions.useClosingBehaviorAbove",
                          )}
                        </option>
                        <option value="keep_chatting">
                          {t(
                            "settings.tenantSettings.leadHandling.closingActionOverrideOptions.keepChatting",
                          )}
                        </option>
                        <option value="escalate_to_human">
                          {t(
                            "settings.tenantSettings.leadHandling.closingActionOverrideOptions.escalateToHuman",
                          )}
                        </option>
                        <option value="book_or_checkout">
                          {t(
                            "settings.tenantSettings.leadHandling.closingActionOverrideOptions.bookOrCheckout",
                          )}
                        </option>
                      </select>
                    </label>
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={
                          settings.behavior_config.lead_handling.hot_lead_requires_purchase_intent
                        }
                        onChange={(e) =>
                          updateArea("lead_handling", {
                            hot_lead_requires_purchase_intent: e.target.checked,
                          })
                        }
                      />
                      {t("settings.tenantSettings.leadHandling.hotLeadRequiresPurchaseIntent")}
                    </label>
                    <AdditionalContextField
                      value={settings.behavior_config.lead_handling.additional_context}
                      onChange={(additional_context) =>
                        updateArea("lead_handling", { additional_context })
                      }
                      label={t("settings.tenantSettings.leadHandling.additionalContext")}
                    />
                  </div>
                )}

                {tab === "escalationCover" && (
                  <div className="tenant-settings__fields">
                    <ToneSelect
                      value={settings.behavior_config.escalation_cover.tone}
                      onChange={(tone) => updateArea("escalation_cover", { tone })}
                      label={t("settings.tenantSettings.tone")}
                    />
                    <AdditionalContextField
                      value={settings.behavior_config.escalation_cover.additional_context}
                      onChange={(additional_context) =>
                        updateArea("escalation_cover", { additional_context })
                      }
                      label={t("settings.tenantSettings.escalationCover.additionalContext")}
                    />
                  </div>
                )}

                {tab === "bookOrCheckout" && (
                  <div className="tenant-settings__fields">
                    <label className="form__field">
                      {t("settings.tenantSettings.bookOrCheckout.ctaStyle")}
                      <select
                        value={settings.behavior_config.book_or_checkout.cta_style}
                        onChange={(e) =>
                          updateArea("book_or_checkout", {
                            cta_style: e.target.value as BookOrCheckoutConfig["cta_style"],
                          })
                        }
                      >
                        <option value="natural_mention">
                          {t("settings.tenantSettings.bookOrCheckout.ctaStyleOptions.naturalMention")}
                        </option>
                        <option value="direct_cta">
                          {t("settings.tenantSettings.bookOrCheckout.ctaStyleOptions.directCta")}
                        </option>
                      </select>
                    </label>
                    <AdditionalContextField
                      value={settings.behavior_config.book_or_checkout.additional_context}
                      onChange={(additional_context) =>
                        updateArea("book_or_checkout", { additional_context })
                      }
                      label={t("settings.tenantSettings.bookOrCheckout.additionalContext")}
                    />
                  </div>
                )}

                {tab === "toolCalling" && (
                  <div className="tenant-settings__fields">
                    <p className="tenant-settings__fields--full form__hint">
                      {t("settings.tenantSettings.toolCalling.simulatedDataNotice")}
                    </p>
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={
                          settings.behavior_config.tool_calling.order_status_lookup_enabled
                        }
                        onChange={(e) =>
                          updateArea("tool_calling", {
                            order_status_lookup_enabled: e.target.checked,
                          })
                        }
                      />
                      {t("settings.tenantSettings.toolCalling.orderStatusLookup")}
                    </label>
                    <label className="form__field form__field--checkbox">
                      <input
                        type="checkbox"
                        checked={settings.behavior_config.tool_calling.inventory_check_enabled}
                        onChange={(e) =>
                          updateArea("tool_calling", {
                            inventory_check_enabled: e.target.checked,
                          })
                        }
                      />
                      {t("settings.tenantSettings.toolCalling.inventoryCheck")}
                    </label>
                    <AdditionalContextField
                      value={settings.behavior_config.tool_calling.additional_context}
                      onChange={(additional_context) =>
                        updateArea("tool_calling", { additional_context })
                      }
                      label={t("settings.tenantSettings.toolCalling.additionalContext")}
                    />
                  </div>
                )}

                {tab === "channels" && (
                  <div className="tenant-settings__fields">
                    {CHANNEL_TYPES.map((channel) => {
                      const override = settings.behavior_config.channel_overrides[channel];
                      return (
                        <div
                          key={channel}
                          className="tenant-settings__channel tenant-settings__fields--full"
                        >
                          <label className="form__field form__field--checkbox">
                            <input
                              type="checkbox"
                              checked={override !== undefined}
                              onChange={(e) => toggleChannelOverride(channel, e.target.checked)}
                            />
                            {t("settings.tenantSettings.channelOverrides.overrideChannel", {
                              channel: t(`channelRail.${channel}`),
                            })}
                          </label>
                          {override && (
                            <div className="tenant-settings__channel-fields tenant-settings__fields">
                              <label className="form__field">
                                {t("settings.tenantSettings.channelOverrides.formality")}
                                <select
                                  value={override.formality}
                                  onChange={(e) =>
                                    updateChannelOverride(channel, {
                                      formality: e.target.value as ChannelToneConfig["formality"],
                                    })
                                  }
                                >
                                  <option value="casual_chat">
                                    {t(
                                      "settings.tenantSettings.channelOverrides.formalityOptions.casualChat",
                                    )}
                                  </option>
                                  <option value="formal_email">
                                    {t(
                                      "settings.tenantSettings.channelOverrides.formalityOptions.formalEmail",
                                    )}
                                  </option>
                                </select>
                              </label>
                              <label className="form__field">
                                {t("settings.tenantSettings.channelOverrides.lengthGuidance")}
                                <select
                                  value={override.length_guidance}
                                  onChange={(e) =>
                                    updateChannelOverride(channel, {
                                      length_guidance: e.target
                                        .value as ChannelToneConfig["length_guidance"],
                                    })
                                  }
                                >
                                  <option value="brief">
                                    {t(
                                      "settings.tenantSettings.channelOverrides.lengthGuidanceOptions.brief",
                                    )}
                                  </option>
                                  <option value="as_needed">
                                    {t(
                                      "settings.tenantSettings.channelOverrides.lengthGuidanceOptions.asNeeded",
                                    )}
                                  </option>
                                </select>
                              </label>
                              <label className="form__field form__field--checkbox">
                                <input
                                  type="checkbox"
                                  checked={override.include_greeting}
                                  onChange={(e) =>
                                    updateChannelOverride(channel, {
                                      include_greeting: e.target.checked,
                                    })
                                  }
                                />
                                {t("settings.tenantSettings.channelOverrides.includeGreeting")}
                              </label>
                              <label className="form__field form__field--checkbox">
                                <input
                                  type="checkbox"
                                  checked={override.include_sign_off}
                                  onChange={(e) =>
                                    updateChannelOverride(channel, {
                                      include_sign_off: e.target.checked,
                                    })
                                  }
                                />
                                {t("settings.tenantSettings.channelOverrides.includeSignOff")}
                              </label>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {tab === "generalContext" && (
                  <div className="tenant-settings__fields">
                    <label className="form__field tenant-settings__fields--full">
                      {t("settings.tenantSettings.generalContext.label")}
                      <textarea
                        maxLength={500}
                        value={settings.behavior_config.general_context ?? ""}
                        onChange={(e) => updateGeneralContext(e.target.value || null)}
                        onKeyDown={(e) =>
                          handleTextareaEnterKey(e, (v) => updateGeneralContext(v || null))
                        }
                        rows={1}
                      />
                    </label>
                  </div>
                )}

                <button
                  type="submit"
                  className="button button--primary button--fit"
                  disabled={savingTab === tab}
                >
                  {savingTab === tab
                    ? t("settings.tenantSettings.saving")
                    : t("settings.tenantSettings.save")}
                </button>
                {saveErrors[tab] && (
                  <p className="error-message" role="alert">
                    {saveErrors[tab]}
                  </p>
                )}
              </form>
                )}
              </>
            )}
          </div>
        </div>
    );
  }

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.settings")}</h1>
      </div>
      <p className="page__description">{t("pages.settings")}</p>

      <div className="settings-columns">
        <div className="settings-column">
          {renderTabNav(LEFT_TAB_ORDER, activeLeftTab, setActiveLeftTab)}
          {renderTabCard(activeLeftTab)}
        </div>
        <div className="settings-column">
          {renderTabNav(RIGHT_TAB_ORDER, activeRightTab, setActiveRightTab)}
          {renderTabCard(activeRightTab)}
        </div>
      </div>
    </section>
  );
}
