import { useEffect, useState } from "react";
import { getHealth } from "./api";
import type { Health } from "./types";

export function useHealth(): { health: Health | null; error: string | null; reload: () => void } {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((value) => {
        if (!cancelled) {
          setHealth(value);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Cannot reach the backend.");
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);
  return { health, error, reload: () => setTick((value) => value + 1) };
}
