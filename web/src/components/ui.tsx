import { createContext, useCallback, useContext, useState } from "react";
import type { CheckResult, Entity, EraSetting, Need, Profile, RuleResult, VerdictKind } from "../api";
import { Link } from "../router";
import { domainLabel, displayTags, favourites, imageOf, initials, leadFavourite, needInfo, otherNotes, pct, sentence, settingNotes, tasteLine, VERDICT, yearOf } from "../lib";
import { Icon } from "./Icon";

/* ---------- verdict stamp & source labels ---------- */
export function Stamp({ verdict, size = "md" }: { verdict: VerdictKind; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`stamp stamp--${verdict} stamp--${size}`} role="img" aria-label={`Verdict: ${VERDICT[verdict].label}`}>
      <span className="stamp__inner">{VERDICT[verdict].label}</span>
    </span>
  );
}

export function Source({ kind }: { kind: "qloo" | "rule" | "setting" }) {
  if (kind === "setting") return <span className="source source--setting"><Icon name="clock" size={14} />Hearth setting</span>;
  return kind === "qloo" ? (
    <span className="source source--qloo"><span className="source__dot" aria-hidden />Qloo taste</span>
  ) : (
    <span className="source source--rule"><Icon name="shield" size={14} />Hearth care rule</span>
  );
}

/* ---------- photo chips ---------- */
export function Photo({ entity, src, name, size = 56, shape = "round" }: {
  entity?: Entity | null; src?: string | null; name?: string; size?: number; shape?: "round" | "card" | "square";
}) {
  const [broken, setBroken] = useState(false);
  const url = src ?? imageOf(entity);
  const label = name ?? entity?.name ?? "";
  return (
    <span className={`photo photo--${shape}`} style={{ width: size, height: shape === "card" ? Math.round(size * 1.25) : size }}>
      <span className="photo__initials" aria-hidden style={{ fontSize: Math.max(12, size * 0.34) }}>{initials(label) || "·"}</span>
      {url && !broken && (
        <img src={url} alt="" decoding="async" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      )}
    </span>
  );
}

export function Collage({ profile, max = 5 }: { profile: Profile; max?: number }) {
  const favs = favourites(profile).slice(0, max);
  if (!favs.length) return <div className="collage collage--empty"><Icon name="plus" /> No favourites yet</div>;
  return (
    <div className="collage" aria-hidden>
      {favs.map((e, i) => (
        <span key={e.id} className="collage__chip" style={{ ["--i" as any]: i }}>
          <Photo entity={e} size={i === 0 ? 92 : 64} shape="square" />
        </span>
      ))}
    </div>
  );
}

/* ---------- needs ---------- */
export function NeedBadge({ need }: { need: Need }) {
  const n = needInfo(need);
  return <span className="need"><Icon name={n.icon} size={16} />{n.label}</span>;
}
export function NeedBadges({ needs }: { needs: Need[] }) {
  if (!needs.length) return <span className="need need--none">No care needs recorded</span>;
  return <span className="needs">{needs.map((n) => <NeedBadge key={n} need={n} />)}</span>;
}

/* ---------- the resident taste card ---------- */
export function TasteCard({ profile, to, tourId }: { profile: Profile; to: string; tourId?: string }) {
  const favs = favourites(profile);
  const line = tasteLine(profile);
  return (
    <Link to={to} className="taste-card" data-tour={tourId} aria-label={`${profile.name}: open taste card`}>
      <span className="taste-card__tab">{favs.length} favourite{favs.length === 1 ? "" : "s"}</span>
      <Collage profile={profile} />
      <span className="taste-card__name">{profile.name}</span>
      <span className="taste-card__line">{line || favs.slice(0, 2).map((f) => f.name).join(" · ") || "Taste not set yet"}</span>
      <span className="taste-card__favs">{favs.slice(0, 3).map((f) => f.name).join(", ")}{favs.length > 3 ? "…" : ""}</span>
      <NeedBadges needs={profile.needs} />
      <span className="taste-card__open">Open card <Icon name="arrow" size={18} /></span>
    </Link>
  );
}

/* ---------- evidence ---------- */
export function EvidenceBlock({ check, rules, residentName, compact }: {
  check: CheckResult | null; rules?: RuleResult[]; residentName: string; compact?: boolean;
}) {
  const lead = leadFavourite(check);
  const ev = check?.evidence;
  const tags = ev?.shared_tags?.length ? displayTags(ev.shared_tags, 4) : [];
  const notes = otherNotes(check);
  const settings = settingNotes(check);
  return (
    <div className={"evidence" + (compact ? " evidence--compact" : "")}>
      {check && (
        <div className="evidence__group">
          <Source kind="qloo" />
          <ul className="evidence__list">
            {lead && <li>Qloo links this most to <strong>{lead.name}</strong> <span className="muted">({lead.share} of the score)</span></li>}
            {tags.length > 0 && (
              <li>Shares <span className="tags">{tags.map((t) => <span key={t} className="tag">{t}</span>)}</span> with {residentName}'s favourites</li>
            )}
            {ev?.relative_fit != null && (
              <li className="fitline">
                <span>Fit: {pct(ev.relative_fit)} of the best Qloo finds for {residentName}</span>
                <span className="meter" aria-hidden><span style={{ width: pct(Math.max(0, (ev.relative_fit - 0.6) / 0.4)) }} /></span>
              </li>
            )}
            {check.resolution?.reason && check.verdict !== "needs_confirmation" && check.verdict !== "cannot_verify" && (
              <li className="muted">{sentence(check.resolution.reason)}</li>
            )}
            {notes.map((n) => <li key={n} className="muted">{sentence(n)}</li>)}
            {!lead && !tags.length && ev?.relative_fit == null && !notes.length && <li className="muted">{sentence(check.resolution?.reason || "No further detail from Qloo.")}</li>}
          </ul>
        </div>
      )}
      {settings.length > 0 && (
        <div className="evidence__group">
          <Source kind="setting" />
          <ul className="evidence__list">
            {settings.map((n) => <li key={n}>{sentence(n)}</li>)}
          </ul>
        </div>
      )}
      {rules && rules.length > 0 && (
        <div className="evidence__group">
          <Source kind="rule" />
          <ul className="rules">
            {rules.map((r) => (
              <li key={r.need + r.reason} className={`rule rule--${r.outcome}`}>
                <span className="rule__mark" aria-hidden><Icon name={r.outcome === "pass" ? "check" : r.outcome === "fail" ? "cross" : "info"} size={16} /></span>
                <span><strong>{needInfo(r.need).label}:</strong> {sentence(r.reason.replace(/; staff to confirm$/, ""))}{r.outcome === "unknown" ? " (staff to confirm)" : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function SwapLine({ check, onUse }: { check: CheckResult; onUse?: (e: Entity) => void }) {
  if (!check.swap) return null;
  const s = check.swap;
  return (
    <div className="swapline">
      <Photo entity={s.entity} size={44} shape="square" />
      <div className="swapline__text">
        <span className="eyebrow">Better fit</span>
        <strong>{s.entity.name}{yearOf(s.entity) ? ` (${yearOf(s.entity)})` : ""}</strong>
        <span className="muted">{sentence(s.reason)} · fit {pct(s.relative_fit)}</span>
      </div>
      {onUse && <button className="btn btn--ghost btn--sm" onClick={() => onUse(s.entity)}><Icon name="swap" size={18} />Use this</button>}
    </div>
  );
}

export function EntityTitle({ e }: { e: Entity }) {
  const y = yearOf(e);
  return <>{e.name}{y ? <span className="muted"> ({y})</span> : null} <span className="kind">{domainLabel(e.type)}</span></>;
}

/* ---------- loading & empty ---------- */
export function Loading({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="loading__flame" aria-hidden><Icon name="flame" size={28} /></span>
      <span className="loading__label">{label}</span>
      <div className="loading__slips" aria-hidden>{Array.from({ length: rows }, (_, i) => <span key={i} className="slip-skeleton" />)}</div>
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <span className="empty__mark" aria-hidden><Icon name="flame" size={30} /></span>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="errornote" role="alert">
      <Icon name="info" /> <span>Something went wrong talking to Hearth: {msg}</span>
      {retry && <button className="btn btn--ghost btn--sm" onClick={retry}>Try again</button>}
    </div>
  );
}

/* ---------- toasts ---------- */
const ToastCtx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string }[]>([]);
  const push = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 6000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite" role="status">
        {items.map((t) => <div key={t.id} className="toast"><Icon name="flame" size={18} />{t.msg}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- film & TV era (a Hearth setting) ---------- */
export function EraPicker({ value, onChange, auto, name, disabled }: {
  value: EraSetting; onChange: (v: EraSetting) => void; auto: number | null; name: string; disabled?: boolean;
}) {
  const thisYear = new Date().getFullYear();
  const [draft, setDraft] = useState(String(value.era_max_year ?? auto ?? 1970));
  const opts: { mode: EraSetting["era_mode"]; label: string; hint: string }[] = [
    { mode: "auto", label: "Automatic", hint: auto ? `Up to ${auto}: newest favourite film + 10 years` : "Add a favourite film or TV programme to set this" },
    { mode: "year", label: "Up to a year", hint: "Choose the latest release year" },
    { mode: "off", label: "Any era", hint: "No limit on release year" },
  ];
  const commitYear = (raw: string) => {
    const y = parseInt(raw, 10);
    if (y >= 1900 && y <= thisYear + 1) onChange({ era_mode: "year", era_max_year: y });
  };
  return (
    <fieldset className="era" disabled={disabled}>
      <legend className="sr-only">Film and TV era for {name}</legend>
      <div className="era__opts" role="radiogroup" aria-label={`Film and TV era for ${name}`}>
        {opts.map((o) => {
          const on = value.era_mode === o.mode;
          return (
            <button key={o.mode} type="button" role="radio" aria-checked={on} className={"era__opt" + (on ? " is-on" : "")}
              onClick={() => (o.mode === "year" ? commitYear(draft) : onChange({ era_mode: o.mode, era_max_year: null }))}>
              <strong>{o.label}</strong><span className="muted small">{o.hint}</span>
            </button>
          );
        })}
      </div>
      {value.era_mode === "year" && (
        <label className="field era__year"><span>Films and TV released up to</span>
          <input type="number" inputMode="numeric" min={1900} max={thisYear + 1} value={draft}
            onChange={(e) => setDraft(e.target.value)} onBlur={(e) => commitYear(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitYear((e.target as HTMLInputElement).value); } }} />
        </label>
      )}
    </fieldset>
  );
}
