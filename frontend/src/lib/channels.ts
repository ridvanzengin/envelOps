import {
  EmailIcon,
  FacebookIcon,
  InstagramIcon,
  TelegramIcon,
  WhatsAppIcon,
} from "../components/icons";

// The one shared source of truth for the five rail channel types --
// previously duplicated independently in ChannelRail.tsx (CHANNELS,
// with icon + real), Settings.tsx (CHANNEL_TYPES), and TestConsole.tsx
// (PLATFORMS, in yet a third order).
export const CHANNEL_TYPES = ["telegram", "whatsapp", "facebook", "instagram", "email"] as const;

export type ChannelType = (typeof CHANNEL_TYPES)[number];

// Icons moved in here once ConversationPanel needed the same mapping
// ChannelRail already had (its own header, next to the platform name) --
// no longer a ChannelRail-only rendering concern.
export const CHANNEL_ICONS: Record<ChannelType, typeof TelegramIcon> = {
  telegram: TelegramIcon,
  whatsapp: WhatsAppIcon,
  facebook: FacebookIcon,
  instagram: InstagramIcon,
  email: EmailIcon,
};

// Only Telegram is a real, built integration (app/channels/api.py's real
// webhook, with actual credentials). The other four are simulated --
// same real pipeline, a webhook-shaped entry point, but no real platform
// is ever contacted (see backend/app/channels/simulated_client.py's own
// docstring for why: this project demonstrates AI behavior orchestration,
// not third-party API integration work).
export const REAL_CHANNEL_TYPES: readonly ChannelType[] = ["telegram"];

export function isRealChannel(channel: ChannelType): boolean {
  return REAL_CHANNEL_TYPES.includes(channel);
}
