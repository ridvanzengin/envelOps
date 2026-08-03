import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { apiGet, apiPatch, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import {
  EmailIcon,
  FacebookIcon,
  InstagramIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "../components/icons";
import { CHANNEL_TYPES, isRealChannel } from "../lib/channels";
import type { ChannelType } from "../lib/channels";
import "./Channels.css";

// Same per-channel icon map ChannelRail.tsx/Settings.tsx/TestConsole.tsx
// each already keep their own copy of -- not centralized in lib/channels.ts
// (that file's own comment says icons stay a rendering concern, not
// coupled into the shared type list), so a fourth small copy here
// follows the existing precedent rather than diverging from it.
const CHANNEL_ICONS: Record<ChannelType, typeof TelegramIcon> = {
  telegram: TelegramIcon,
  whatsapp: WhatsAppIcon,
  facebook: FacebookIcon,
  instagram: InstagramIcon,
  email: EmailIcon,
};

interface ApiChannel {
  id: string;
  type: string;
  status: string;
  ai_enabled: boolean;
}

export default function Channels() {
  const { t } = useTranslation();
  const { token, logout } = useAuth();

  const [channels, setChannels] = useState<ApiChannel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const result = await apiGet<ApiChannel[]>("/channels/connected", token);
      setChannels(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setLoadError(t("channels.loadError"));
    }
  }, [token, logout, t]);

  useEffect(() => {
    void load();
  }, [load]);

  // Real channels are 0-or-1 per type in practice (each registration
  // script creates exactly one), but grouped as a list rather than a
  // single lookup -- nothing here assumes a hard limit of one.
  const channelsByType = useMemo(() => {
    const map: Partial<Record<ChannelType, ApiChannel[]>> = {};
    for (const channel of channels ?? []) {
      const key = channel.type as ChannelType;
      (map[key] ??= []).push(channel);
    }
    return map;
  }, [channels]);

  async function handleToggle(channel: ApiChannel) {
    const nextEnabled = !channel.ai_enabled;
    setToggleError(null);
    setTogglingId(channel.id);
    setChannels(
      (prev) =>
        prev?.map((c) => (c.id === channel.id ? { ...c, ai_enabled: nextEnabled } : c)) ?? prev,
    );
    try {
      await apiPatch(`/channels/${channel.id}`, { ai_enabled: nextEnabled }, token);
    } catch (err) {
      // Revert the optimistic flip -- the switch must reflect what's
      // actually persisted, not what the user clicked.
      setChannels(
        (prev) =>
          prev?.map((c) =>
            c.id === channel.id ? { ...c, ai_enabled: channel.ai_enabled } : c,
          ) ?? prev,
      );
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setToggleError(t("channels.toggleError"));
    } finally {
      setTogglingId(null);
    }
  }

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.channels")}</h1>
        <div className="channels__toolbar">
          <button type="button" className="button" disabled title={t("channels.comingSoon")}>
            {t("channels.testAllChannels")}
          </button>
          <button type="button" className="button" disabled title={t("channels.comingSoon")}>
            {t("channels.addChannel")}
          </button>
        </div>
      </div>
      <p className="page__description">{t("pages.channels")}</p>

      {loadError && (
        <p className="error-message" role="alert">
          {loadError}
        </p>
      )}
      {toggleError && (
        <p className="error-message" role="alert">
          {toggleError}
        </p>
      )}
      {channels === null && !loadError && <p>{t("channels.loading")}</p>}

      {channels !== null && (
        <div className="card">
          <ul className="channels__list">
            {CHANNEL_TYPES.map((type) => {
              const Icon = CHANNEL_ICONS[type];
              const real = isRealChannel(type);
              // 0-or-1 in practice (each registration script creates
              // exactly one real channel per type) -- takes the first if
              // more than one ever exists, doesn't assume a hard limit.
              const channel = channelsByType[type]?.[0];

              return (
                <li key={type} className="channels__row">
                  <span className="channels__row-icon">
                    <Icon />
                  </span>
                  <span className="channels__row-name">{t(`channelRail.${type}`)}</span>
                  <span className={`channels__badge${real ? " channels__badge--real" : ""}`}>
                    {real
                      ? t("channelRail.realIntegration")
                      : t("channelRail.simulatedIntegration")}
                  </span>
                  <label
                    className="toggle-switch"
                    title={channel ? undefined : t("channels.notSetUp")}
                  >
                    <input
                      type="checkbox"
                      className="toggle-switch__input"
                      checked={channel ? channel.ai_enabled : false}
                      disabled={!channel || togglingId === channel.id}
                      onChange={() => channel && void handleToggle(channel)}
                      aria-label={t("channels.autoReplyToggleLabel")}
                    />
                    <span className="toggle-switch__track">
                      <span className="toggle-switch__thumb" />
                    </span>
                  </label>
                  <span className="channels__row-status">
                    {channel &&
                      (channel.ai_enabled ? t("channels.autoReplyOn") : t("channels.autoReplyOff"))}
                  </span>
                  <button
                    type="button"
                    className="button"
                    disabled
                    title={t("channels.comingSoon")}
                  >
                    {t("channels.configure")}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <p className="channels__settings-link">
        {t("channels.settingsLinkText")}{" "}
        <Link to="/settings">{t("channels.settingsLinkLabel")}</Link>
      </p>
    </section>
  );
}
