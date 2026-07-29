// Mirrors iotops-workspace's own utils/debounce.ts -- used by
// ConversationPanelContext so a burst of SSE events (several messages in
// quick succession) triggers one refetch, not one per event.
export function debounce<Args extends unknown[]>(
  fn: (...args: Args) => void,
  delayMs: number,
): (...args: Args) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Args) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}
