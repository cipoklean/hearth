import { useCallback, useEffect, useState } from "react";
import { api, type WeeklyPlan } from "./api";

// Swaps are remembered per resident in this browser: the plan is re-asked with those picks skipped.
interface Skips { ids: string[]; cuisines: string[] }
const key = (rid: string) => `hearth.skip.${rid}`;
export const loadSkips = (rid: string): Skips => {
  try { return { ids: [], cuisines: [], ...JSON.parse(localStorage.getItem(key(rid)) || "{}") }; }
  catch { return { ids: [], cuisines: [] }; }
};
const saveSkips = (rid: string, s: Skips) => localStorage.setItem(key(rid), JSON.stringify(s));

export function usePlan(rid: string) {
  const [plan, setPlan] = useState<WeeklyPlan | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busySlot, setBusySlot] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError(null);
    try {
      const s = loadSkips(rid);
      const p = await api.plan(rid, s.ids, s.cuisines);
      setPlan(p);
      return p;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, [rid]);

  useEffect(() => { load(); }, [load]);

  const swap = useCallback(async (slotKey: string, entityId?: string, cuisine?: string | null) => {
    const s = loadSkips(rid);
    if (entityId) s.ids = [...new Set([...s.ids, entityId])];
    if (cuisine) s.cuisines = [...new Set([...s.cuisines, cuisine])];
    saveSkips(rid, s);
    setBusySlot(slotKey);
    const p = await load(true);
    setBusySlot(null);
    return p;
  }, [rid, load]);

  const resetSwaps = useCallback(async () => {
    saveSkips(rid, { ids: [], cuisines: [] });
    await load();
  }, [rid, load]);

  return { plan, error, loading, reload: load, swap, resetSwaps, busySlot, setBusySlot,
    swapped: () => { const s = loadSkips(rid); return s.ids.length + s.cuisines.length; } };
}
