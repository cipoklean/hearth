import type { CheckResult, Entity, Need, Profile, Tag, VerdictKind } from "./api";

export const NEEDS: { key: Need; label: string; hint: string; icon: string }[] = [
  { key: "soft_food", label: "Soft food", hint: "Easy to chew and swallow", icon: "spoon" },
  { key: "low_salt", label: "Low salt", hint: "Heart or blood-pressure diet", icon: "salt" },
  { key: "low_sugar", label: "Low sugar", hint: "Diabetic-friendly choices", icon: "cube" },
  { key: "vegetarian", label: "Vegetarian", hint: "No meat or fish", icon: "leaf" },
  { key: "wheelchair_access", label: "Wheelchair", hint: "Step-free outings only", icon: "wheel" },
  { key: "hearing_support", label: "Hard of hearing", hint: "Subtitles and hearing loop", icon: "ear" },
  { key: "quiet_setting", label: "Quiet setting", hint: "No loud venues or genres", icon: "quiet" },
  { key: "short_duration", label: "Short sessions", hint: "Films under 1 h 45", icon: "clock" },
  { key: "mild_content", label: "Gentle films", hint: "No horror, war or R-rated", icon: "heart" },
];
export const needInfo = (n: Need) => NEEDS.find((x) => x.key === n)!;

export const DOMAINS = [
  { key: "artist", label: "Music", noun: "singer or band", icon: "note", example: "e.g. Ella Fitzgerald" },
  { key: "movie", label: "Films", noun: "film", icon: "film", example: "e.g. Casablanca" },
  { key: "tv_show", label: "TV", noun: "TV programme", icon: "tv", example: "e.g. Dad's Army" },
  { key: "place", label: "Places", noun: "place", icon: "pin", example: "e.g. Kew Gardens" },
] as const;
export type DomainKey = (typeof DOMAINS)[number]["key"];

export const kindOf = (type: string) => type.split(":").pop() || type;
export const domainLabel = (type: string) => {
  const k = kindOf(type);
  return { artist: "Music", movie: "Film", tv_show: "TV", place: "Place", book: "Book" }[k] || k;
};

export const imageOf = (e?: { properties?: Record<string, any> } | null): string | null => {
  const img = e?.properties?.image;
  if (!img) return null;
  return typeof img === "string" ? img : img.url || null;
};
export const yearOf = (e?: Entity | null) =>
  (e?.properties?.release_year as number | undefined) ?? (e?.properties?.publication_year as number | undefined);

const TAG_RANK = ["genre", "subgenre", "style", "influence", "category", "music", "theme", "plot", "setting",
  "ambience", "activity_type", "instrument", "interests", "archetype", "character", "artist", "characteristic",
  "keyword", "audience"];
const tagRank = (id: string) => {
  const cat = id.split(":")[2] || "";
  const i = TAG_RANK.indexOf(cat);
  return i < 0 ? TAG_RANK.length : i;
};
/** Genre/style words first, audience adjectives last; de-duplicated by name. */
export function displayTags(tags: Tag[], n = 3): string[] {
  const seen = new Set<string>();
  return [...tags]
    .filter((t) => t.name && !t.id.includes(":obscurity:") && !t.id.includes(":time_of_day_fit:"))
    .sort((a, b) => tagRank(a.id) - tagRank(b.id))
    .filter((t) => { const k = t.name.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; })
    .slice(0, n).map((t) => t.name);
}

/** "Swing · Jazz · Classic film": the genre words their confirmed favourites share most. */
export function tasteLine(p: Profile, n = 3): string {
  const count = new Map<string, number>();
  for (const e of p.entities) {
    if ((e.weight ?? 1) <= 0 || p.disliked.includes(e.id)) continue;
    const seen = new Set<string>();
    for (const t of e.tags) {
      if (!t.name || !/:(genre|subgenre):/.test(t.id)) continue;
      const k = t.name;
      if (seen.has(k)) continue;
      seen.add(k);
      count.set(k, (count.get(k) || 0) + 1);
    }
  }
  return [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n).map(([k]) => k).join(" · ");
}

export const favourites = (p: Profile) =>
  p.entities.filter((e) => (e.weight ?? 1) > 0 && !p.disliked.includes(e.id))
    .sort((a, b) => kindOrder(a.type) - kindOrder(b.type));
const kindOrder = (t: string) => ["artist", "movie", "tv_show", "place"].indexOf(kindOf(t));

export const VERDICT: Record<VerdictKind, { label: string; short: string }> = {
  good: { label: "Good fit", short: "Good" },
  weak: { label: "Weak fit", short: "Weak" },
  poor: { label: "Poor fit", short: "Poor" },
  cannot_verify: { label: "Can't verify", short: "Unknown" },
  needs_confirmation: { label: "Confirm which one", short: "Confirm" },
};

/** The favourite Qloo's explainability says drives this score, if the verifier surfaced one. */
export function leadFavourite(c?: CheckResult | null): { name: string; share: string } | null {
  for (const n of c?.evidence?.notes || []) {
    const m = n.match(/^Qloo links this most to (.+) \((\d+%) of the score\)$/);
    if (m) return { name: m[1], share: m[2] };
  }
  return null;
}
export const otherNotes = (c?: CheckResult | null) =>
  (c?.evidence?.notes || []).filter((n) => !/^Qloo links this most to/.test(n));

export const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");

export const SLOT: Record<string, { label: string; icon: string; time: string }> = {
  meal_theme: { label: "Lunch theme", icon: "plate", time: "12:30" },
  music_session: { label: "Music session", icon: "note", time: "14:30" },
  film_night: { label: "Film night", icon: "film", time: "18:30" },
  outing: { label: "Outing", icon: "pin", time: "10:30" },
};
export const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function sentence(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
