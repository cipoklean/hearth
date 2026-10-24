import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type Home, type Profile } from "./api";

interface HomeState {
  home: Home | null;
  residents: Profile[] | null;
  error: unknown;
  refresh: () => Promise<void>;
  setResidents: (r: Profile[]) => void;
}

const Ctx = createContext<HomeState>(null as any);
export const useHome = () => useContext(Ctx);

export function HomeProvider({ children }: { children: React.ReactNode }) {
  const [home, setHome] = useState<Home | null>(null);
  const [residents, setResidents] = useState<Profile[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const refresh = useCallback(async () => {
    try {
      const [h, r] = await Promise.all([api.home(), api.residents()]);
      setHome(h);
      setResidents(r);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return <Ctx.Provider value={{ home, residents, error, refresh, setResidents }}>{children}</Ctx.Provider>;
}

/** Small async-data hook with reload. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setData(await fn()); } catch (e) { setError(e); } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run, setData };
}
