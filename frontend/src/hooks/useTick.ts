import { useEffect, useState } from "react";

// Forces a re-render every `intervalMs` -- used by anything displaying a
// relative time ("5m ago") so it doesn't go stale while a conversation
// panel/thread stays open. The returned value has no meaning of its own,
// components just need to read it so React knows to re-render each tick.
export function useTick(intervalMs: number): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((value) => value + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return tick;
}
