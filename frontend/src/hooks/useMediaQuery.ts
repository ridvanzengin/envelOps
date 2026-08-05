import { useEffect, useState } from "react";

// The one standard "phone-sized viewport" breakpoint for this app's mobile
// pass -- shared by Sidebar, ChannelRail, and ConversationPanel rather than
// each picking its own value. Same breakpoint as the sibling reference
// project's own mobile pass (iotops-workspace/IoTOps).
export const MOBILE_QUERY = "(max-width: 640px)";

// Backed by matchMedia's own live MediaQueryList rather than a resize
// listener + manual width comparison, so it also reacts to e.g. rotating a
// device or a DevTools breakpoint change without re-deriving anything.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mediaQueryList = window.matchMedia(query);
    const listener = () => setMatches(mediaQueryList.matches);
    listener();
    mediaQueryList.addEventListener("change", listener);
    return () => mediaQueryList.removeEventListener("change", listener);
  }, [query]);

  return matches;
}
