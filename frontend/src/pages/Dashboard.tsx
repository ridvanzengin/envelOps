import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiGet, apiPost, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { DonutChart } from "../components/dashboard/DonutChart";
import { StatTile } from "../components/dashboard/StatTile";
import { TrendChart } from "../components/dashboard/TrendChart";
import {
  AlertTriangleIcon,
  ChatIcon,
  CheckIcon,
  ChevronIcon,
  ClockIcon,
  EmailIcon,
  FacebookIcon,
  FlagIcon,
  InstagramIcon,
  StoreIcon,
  TargetIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "../components/icons";
import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { useDemoModeContext } from "../context/demoMode/useDemoModeContext";
import { useDemoTenants } from "../hooks/useDemoTenants";
import { decodeJwtPayload } from "../lib/jwt";
import { formatRelativeTime } from "../utils/relativeTime";
import "./Dashboard.css";

interface DemoLoginResponse {
  access_token: string;
  token_type: string;
}

interface TrendPoint {
  date: string;
  count: number;
}

interface IntentBreakdownItem {
  intent: string;
  count: number;
  percentage: number;
}

interface ChannelStat {
  channel_type: string;
  conversations: number;
  resolution_rate: number | null;
}

interface DashboardSummary {
  range_days: number;
  total_conversations: number;
  total_conversations_prev: number;
  hot_leads: number;
  hot_leads_prev: number;
  complaints: number;
  complaints_prev: number;
  escalated: number;
  escalated_prev: number;
  avg_response_minutes: number | null;
  conversations_trend: TrendPoint[];
  hot_leads_trend: TrendPoint[];
  complaints_trend: TrendPoint[];
  escalated_trend: TrendPoint[];
  intent_breakdown: IntentBreakdownItem[];
  channels: ChannelStat[];
}

interface KnowledgeSource {
  id: string;
  type: string;
  source_uri: string | null;
  last_synced_at: string | null;
  chunk_count: number;
  content: string;
}

const RANGE_OPTIONS = [1, 7, 30] as const;
type RangeDays = (typeof RANGE_OPTIONS)[number];

const CHANNEL_ICONS: Record<string, typeof TelegramIcon> = {
  telegram: TelegramIcon,
  whatsapp: WhatsAppIcon,
  facebook: FacebookIcon,
  instagram: InstagramIcon,
  email: EmailIcon,
};

// Mirrors KnowledgeSources.tsx's own sourceTitle exactly -- a knowledge
// source has no dedicated title field (docs/ARCHITECTURE.md's data model
// never grew one), so both pages derive one the same way. Not extracted
// into a shared util for one extra call site; flagged here rather than
// silently diverging if KnowledgeSources.tsx's version ever changes.
function sourceTitle(source: KnowledgeSource): string {
  if (source.source_uri) return source.source_uri;
  const words = source.content.trim().split(/\s+/).slice(0, 6);
  return words.length > 0 ? `${words.join(" ")}…` : source.content;
}

export default function Dashboard() {
  const { t, i18n } = useTranslation();
  const { token, logout, loginWithToken } = useAuth();
  const { enabled: demoModeEnabled } = useDemoModeContext();
  const demoTenants = useDemoTenants();
  const { closePanel } = useConversationPanel();
  const currentTenantId = token
    ? (decodeJwtPayload<{ tenant_id: string }>(token)?.tenant_id ?? null)
    : null;
  const currentTenant = demoTenants.find((option) => option.tenant_id === currentTenantId);
  const [tenantMenuOpen, setTenantMenuOpen] = useState(false);

  // Same click-outside convention as every other .dropdown-menu consumer
  // (ChannelRail.tsx) -- a mousedown anywhere outside the menu's own DOM
  // subtree closes it.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!(event.target instanceof Element) || !event.target.closest(".dropdown-menu")) {
        setTenantMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function handleTenantSwitch(tenantId: string) {
    setTenantMenuOpen(false);
    const tenant = demoTenants.find((option) => option.tenant_id === tenantId);
    if (!tenant || tenantId === currentTenantId) return;
    const response = await apiPost<DemoLoginResponse>(
      "/auth/demo-login",
      { user_id: tenant.user_id },
      null,
    );
    loginWithToken(response.access_token);
    // The conversation rail's own conversations/channels belong to
    // whichever tenant it was opened under -- left open across a switch,
    // it would keep showing the previous tenant's data under the new
    // one's identity until manually closed and reopened.
    closePanel();
  }

  const [days, setDays] = useState<RangeDays>(7);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[] | null>(null);

  const loadSummary = useCallback(async () => {
    setSummaryError(null);
    try {
      const result = await apiGet<DashboardSummary>(`/dashboard/summary?days=${days}`, token);
      setSummary(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSummaryError(t("dashboard.loadError"));
    }
  }, [token, logout, t, days]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    apiGet<KnowledgeSource[]>("/knowledge/sources", token)
      .then(setKnowledgeSources)
      .catch(() => setKnowledgeSources([]));
  }, [token]);

  const knowledgeStats = useMemo(() => {
    if (!knowledgeSources) return null;
    const totalChunks = knowledgeSources.reduce((sum, source) => sum + source.chunk_count, 0);
    const recent = [...knowledgeSources]
      .sort((a, b) => {
        const aTime = a.last_synced_at ? new Date(a.last_synced_at).getTime() : 0;
        const bTime = b.last_synced_at ? new Date(b.last_synced_at).getTime() : 0;
        return bTime - aTime;
      })
      .slice(0, 4);
    return { totalSources: knowledgeSources.length, totalChunks, recent };
  }, [knowledgeSources]);

  // The "1 day" range buckets by hour, not calendar day (backend's own
  // compute_summary), so its trend points need a time-of-day label
  // ("2:00 PM"), not a date one -- a date label would repeat the same
  // string 24 times in a row.
  function formatDate(isoDate: string): string {
    if (days === 1) {
      return new Date(isoDate).toLocaleTimeString(i18n.language, {
        hour: "numeric",
        minute: "2-digit",
      });
    }
    return new Date(isoDate).toLocaleDateString(i18n.language, {
      month: "short",
      day: "numeric",
    });
  }

  return (
    <section className="page">
      <div className="page__header">
        {demoModeEnabled ? (
          <div className="dashboard__tenant-switch dropdown-menu">
            <button
              type="button"
              className="dashboard__tenant-switch-trigger"
              aria-label={`${t("demoMode.tenantLabel")}: ${currentTenant?.tenant_name ?? t("app.loading")}`}
              aria-expanded={tenantMenuOpen}
              onClick={() => setTenantMenuOpen((value) => !value)}
            >
              <span className="dashboard__tenant-switch-icon">
                <StoreIcon />
              </span>
              <span className="dashboard__tenant-switch-name">
                {currentTenant?.tenant_name ?? t("app.loading")}
              </span>
              <ChevronIcon
                className={`chevron dashboard__tenant-switch-chevron${
                  tenantMenuOpen ? " chevron--expanded" : ""
                }`}
              />
            </button>
            {tenantMenuOpen && (
              <div className="dropdown-menu__list dashboard__tenant-switch-list">
                {demoTenants.map((tenant) => (
                  <button
                    key={tenant.tenant_id}
                    type="button"
                    className="dropdown-menu__item"
                    onClick={() => void handleTenantSwitch(tenant.tenant_id)}
                  >
                    <span className="dashboard__tenant-switch-item-text">
                      <span>{tenant.tenant_name}</span>
                      <span className="dashboard__tenant-switch-item-email">{tenant.email}</span>
                    </span>
                    {tenant.tenant_id === currentTenantId && (
                      <CheckIcon className="dropdown-menu__item-icon" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <h1>{t("nav.dashboard")}</h1>
        )}
        <div className="dashboard__range" role="group" aria-label={t("dashboard.rangeLabel")}>
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={
                days === option
                  ? "dashboard__range-option dashboard__range-option--active"
                  : "dashboard__range-option"
              }
              onClick={() => setDays(option)}
            >
              {/* "1 day" reads as a calendar-day toggle; the backend
                  actually buckets it as a rolling last-24-hours window
                  (see formatDate above), so the label says what it does. */}
              {option === 1 ? t("dashboard.range24Hours") : t("dashboard.rangeDays", { count: option })}
            </button>
          ))}
        </div>
      </div>

      {summaryError && (
        <p className="error-message" role="alert">
          {summaryError}
        </p>
      )}
      {summary === null && !summaryError && <p>{t("dashboard.loading")}</p>}

      {summary && (
        <div className="dashboard__sections">
          <div className="dashboard__stats">
            <StatTile
              label={t("dashboard.statConversations")}
              value={summary.total_conversations}
              prevValue={summary.total_conversations_prev}
              sparklineValues={summary.conversations_trend.map((p) => p.count)}
              icon={<ChatIcon />}
            />
            <StatTile
              label={t("dashboard.statHotLeads")}
              value={summary.hot_leads}
              prevValue={summary.hot_leads_prev}
              sparklineValues={summary.hot_leads_trend.map((p) => p.count)}
              icon={<TargetIcon />}
            />
            <StatTile
              label={t("dashboard.statComplaints")}
              value={summary.complaints}
              prevValue={summary.complaints_prev}
              increaseIsGood={false}
              sparklineValues={summary.complaints_trend.map((p) => p.count)}
              icon={<FlagIcon />}
            />
            <StatTile
              label={t("dashboard.statEscalated")}
              value={summary.escalated}
              prevValue={summary.escalated_prev}
              increaseIsGood={false}
              sparklineValues={summary.escalated_trend.map((p) => p.count)}
              icon={<AlertTriangleIcon />}
            />
            <StatTile
              label={t("dashboard.statResponseTime")}
              value={summary.avg_response_minutes}
              formatValue={(value) =>
                value > 0 && value < 1
                  ? t("dashboard.underAMinute")
                  : t("dashboard.minutes", { count: Math.round(value) })
              }
              icon={<ClockIcon />}
            />
          </div>

          <div className="dashboard__row">
            <div className="card dashboard__panel">
              <h2>{t("dashboard.conversationsOverTime")}</h2>
              <TrendChart points={summary.conversations_trend} formatDate={formatDate} />
            </div>
            <div className="card dashboard__panel">
              <h2>{t("dashboard.conversationsByIntent")}</h2>
              {summary.intent_breakdown.length > 0 ? (
                <DonutChart
                  items={summary.intent_breakdown}
                  labelFor={(intent) => t(`diagnostics.intent.${intent}`, intent)}
                />
              ) : (
                <div className="empty-state">{t("dashboard.noIntentData")}</div>
              )}
            </div>
          </div>

          <div className="dashboard__row">
            <div className="card dashboard__panel">
              <h2>{t("dashboard.topChannels")}</h2>
              {summary.channels.length > 0 ? (
                <div className="table-wrapper">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("dashboard.channel")}</th>
                        <th>{t("dashboard.conversations")}</th>
                        <th>{t("dashboard.resolutionRate")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.channels.map((channel) => {
                        const Icon = CHANNEL_ICONS[channel.channel_type];
                        return (
                          <tr key={channel.channel_type}>
                            <td className="dashboard__channel-cell">
                              {Icon && <Icon />}
                              {t(`channelRail.${channel.channel_type}`, channel.channel_type)}
                            </td>
                            <td>{channel.conversations}</td>
                            <td>
                              {channel.resolution_rate === null
                                ? "—"
                                : `${Math.round(channel.resolution_rate * 100)}%`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty-state">{t("dashboard.noChannelData")}</div>
              )}
            </div>

            <div className="card dashboard__panel">
              <h2>{t("dashboard.knowledgeStatus")}</h2>
              {knowledgeStats === null ? (
                <p>{t("dashboard.loading")}</p>
              ) : (
                <>
                  <div className="dashboard__knowledge-summary">
                    <div>
                      <span className="dashboard__knowledge-summary-value">
                        {knowledgeStats.totalSources}
                      </span>
                      <span className="dashboard__knowledge-summary-label">
                        {t("dashboard.sources")}
                      </span>
                    </div>
                    <div>
                      <span className="dashboard__knowledge-summary-value">
                        {knowledgeStats.totalChunks}
                      </span>
                      <span className="dashboard__knowledge-summary-label">
                        {t("dashboard.chunks")}
                      </span>
                    </div>
                  </div>
                  {knowledgeStats.recent.length > 0 ? (
                    <ul className="dashboard__knowledge-list">
                      {knowledgeStats.recent.map((source) => (
                        <li key={source.id} className="dashboard__knowledge-row">
                          <span className="dashboard__knowledge-row-title">
                            {sourceTitle(source)}
                          </span>
                          <span className="dashboard__knowledge-row-meta">
                            {t("dashboard.chunkCount", { count: source.chunk_count })}
                            {source.last_synced_at &&
                              ` · ${formatRelativeTime(source.last_synced_at, i18n.language, t("time.justNow"))}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="empty-state">{t("dashboard.noKnowledgeSources")}</div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
