// Thin typed client for Hearth's JSON API (/api). Each browser has its own care home,
// identified by a random id kept in localStorage (no account, no personal data).

export type Need =
  | "soft_food" | "low_salt" | "low_sugar" | "vegetarian" | "wheelchair_access"
  | "quiet_setting" | "hearing_support" | "short_duration" | "mild_content";

export interface Tag { id: string; name: string; type?: string; weight?: number }
export interface Entity {
  id: string; name: string; type: string; tags: Tag[];
  properties: Record<string, any>; weight?: number;
}
export type EraMode = "auto" | "year" | "off";
export interface Era { max_year: number; source: "auto" | "set"; explanation: string; label: string }
export interface EraSetting { era_mode: EraMode; era_max_year: number | null }
export interface Profile extends EraSetting {
  resident_id: string; name: string; entities: Entity[]; tags: Tag[];
  disliked: string[]; needs: Need[]; era: Era | null;
}
export interface Home { id: string; name: string; city: string; demo: boolean; residents?: number; mock?: boolean }

export type VerdictKind = "good" | "weak" | "poor" | "needs_confirmation" | "cannot_verify";
export interface Resolution { status: "resolved" | "ambiguous" | "cannot_verify"; entity: Entity | null; options: Entity[]; reason: string }
export interface Evidence {
  qloo_affinity: number | null; best_available_affinity: number | null; relative_fit: number | null;
  shared_tags: Tag[]; signal_contributions: { entity_id: string; name: string; share: number }[];
  threshold_status: string; notes: string[];
}
export interface Swap { entity: Entity; qloo_affinity: number; relative_fit: number; shared_tags: Tag[]; reason: string }
export interface Candidate { name: string; domain: string; entity_id?: string | null }
export interface CheckResult { candidate: Candidate; resolution: Resolution; verdict: VerdictKind; evidence: Evidence; swap: Swap | null }
export interface VerifyReport { profile_name: string; results: CheckResult[]; counts: Record<string, number>; source_note: string }

export interface RuleResult { need: Need; outcome: "pass" | "fail" | "unknown"; reason: string; label: string }
export interface Dish { name: string; cuisine: string; soft: boolean; low_salt: boolean; low_sugar: boolean; vegetarian: boolean }
export interface PlanItem {
  day: string; slot: "meal_theme" | "music_session" | "film_night" | "outing"; title: string;
  entity: Entity | null; check: CheckResult | null; rules: RuleResult[]; dishes: Dish[];
  evidence_places: string[]; cuisine: string | null; notes: string[];
}
export interface WeeklyPlan { resident_id: string; name: string; items: PlanItem[]; source_note: string; notes?: string[] }

export interface ResidentFit { resident_id: string; name: string; relative_fit: number; qloo_affinity: number; verdict: VerdictKind; shared_tags: Tag[] }
export interface LeftOut { resident_id: string; name: string; relative_fit: number; alternative: Entity | null; alternative_fit: number | null; reason: string }
export interface GroupPick {
  domain: string; pick: Entity | null; fits: ResidentFit[]; left_out: LeftOut[];
  excluded: { entity: Entity; reason: string }[]; unresolved: Resolution[]; considered: number; notes: string[];
}
export interface SearchHit {
  id: string; name: string; type: string; image: string | null; year: number | null;
  disambiguation: string | null; popularity: number | null; display_tags: string[]; tags: Tag[];
}
export interface HistoryRow { entity_id: string; name: string; type: string; enjoyed: boolean; created_at: string }

/** Start a fresh, empty home in this browser (used when leaving the sample home). */
export function newHomeId(): void {
  localStorage.removeItem("hearth.home");
  homeId();
}

function homeId(): string {
  let id = localStorage.getItem("hearth.home");
  if (!id) {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    id = "h-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("hearth.home", id);
  }
  return id;
}

// Set VITE_API_BASE (e.g. https://hearth.example.com) when the frontend is hosted apart from the API.
const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const TIMEOUT_MS = 45_000;

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    return await fetch(API_BASE + "/api" + path, {
      method,
      headers: { "X-Hearth-Home": homeId(), ...(body ? { "content-type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctl.signal,
    });
  } catch (e) {
    if (ctl.signal.aborted) throw new ApiError(0, "Hearth is taking longer than usual. Please try again.");
    throw new ApiError(0, "Couldn't reach Hearth. Check your connection, then try again.");
  } finally {
    clearTimeout(timer);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await send(method, path, body);
  } catch (e) {
    // One quiet retry for reads: a server restart or a dropped mobile packet shouldn't greet anyone.
    if (method !== "GET" || (e as ApiError).message.startsWith("Hearth is taking")) throw e;
    await new Promise((r) => setTimeout(r, 1200));
    res = await send(method, path, body);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const qs = (o: Record<string, string | string[] | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else if (v !== undefined) p.set(k, v);
  }
  const s = p.toString();
  return s ? "?" + s : "";
};

// Release year travels with a favourite: it sets the resident's automatic film/TV era.
const entityIn = (e: Entity) => {
  const y = e.properties?.release_year;
  return { id: e.id, name: e.name, type: e.type, tags: e.tags.slice(0, 20), ...(typeof y === "number" ? { year: y } : {}) };
};

export const api = {
  home: () => req<Home>("GET", "/home"),
  setHome: (name?: string, city?: string) => req<Home>("PUT", "/home", { name, city }),
  eraseHome: () => req<{ deleted_residents: number }>("DELETE", "/home"),
  seedDemo: () => req<{ home: Home; created: number }>("POST", "/demo"),
  residents: () => req<Profile[]>("GET", "/residents"),
  resident: (id: string) => req<Profile>("GET", `/residents/${id}`),
  createResident: (name: string, entities: Entity[], needs: Need[], era?: EraSetting) =>
    req<Profile>("POST", "/residents", {
      name, needs, ...(era || {}),
      entities: entities.map(entityIn),
    }),
  setEra: (id: string, era: EraSetting) => req<Profile>("PUT", `/residents/${id}/era`, era),
  deleteResident: (id: string) => req<void>("DELETE", `/residents/${id}`),
  history: (id: string) => req<HistoryRow[]>("GET", `/residents/${id}/history`),
  plan: (id: string, skip: string[] = [], skipCuisine: string[] = []) =>
    req<WeeklyPlan>("GET", `/residents/${id}/plan${qs({ skip, skip_cuisine: skipCuisine })}`),
  verify: (residentId: string, candidates: Candidate[]) =>
    req<VerifyReport>("POST", "/verify", { resident_id: residentId, candidates }),
  groupPick: (ids: string[], domain: string) => req<GroupPick>("POST", "/group-pick", { resident_ids: ids, domain }),
  feedback: (residentId: string, entity: Entity, enjoyed: boolean) =>
    req<Profile>("POST", "/feedback", {
      resident_id: residentId, enjoyed,
      entity: entityIn(entity),
    }),
  search: (q: string, domain: string) =>
    req<{ results: SearchHit[] }>("GET", `/search${qs({ q, domain })}`),
};
