// Abbreviated units (m/h/d) rather than full words -- sidesteps needing
// i18next plural-form keys entirely ("5m ago" and "1m ago" don't need
// separate singular/plural strings the way "5 minutes ago"/"1 minute ago"
// would), and matches the common chat-app convention (WhatsApp/Telegram)
// this is modeled on. Falls back to a short absolute date once a message
// is old enough that "how long ago" stops being the useful framing.
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const RECENT_CUTOFF_MS = 7 * DAY_MS;

export function formatRelativeTime(isoString: string, locale: string, justNowLabel: string): string {
  const then = new Date(isoString).getTime();
  const diffMs = Date.now() - then;

  if (diffMs < MINUTE_MS) {
    return justNowLabel;
  }
  if (diffMs < HOUR_MS) {
    return `${Math.floor(diffMs / MINUTE_MS)}m`;
  }
  if (diffMs < DAY_MS) {
    return `${Math.floor(diffMs / HOUR_MS)}h`;
  }
  if (diffMs < RECENT_CUTOFF_MS) {
    return `${Math.floor(diffMs / DAY_MS)}d`;
  }
  return new Date(isoString).toLocaleDateString(locale, { month: "short", day: "numeric" });
}
