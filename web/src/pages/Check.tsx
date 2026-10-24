import { useMemo, useState } from "react";
import { api, type CheckResult, type Entity } from "../api";
import { Icon } from "../components/Icon";
import { Collage, Empty, EvidenceBlock, ErrorNote, Loading, Photo, Stamp, SwapLine } from "../components/ui";
import { DOMAINS, type DomainKey, sentence, VERDICT, yearOf } from "../lib";
import { Link } from "../router";
import { useHome } from "../state";

// Example lists (names only) so first-time visitors can try the checker in one tap.
const EXAMPLES_LIVE: Record<DomainKey, string[]> = {
  movie: ["An Affair to Remember", "The Philadelphia Story", "Mamma Mia!", "Saw", "Little Women", "Fast & Furious 6"],
  artist: ["Nat King Cole", "Doris Day", "Michael Bublé", "Slipknot", "Aretha Franklin"],
  tv_show: ["Dad's Army", "The Good Life", "Breaking Bad", "Downton Abbey"],
  place: ["Royal Albert Hall", "Kew Gardens", "Ministry of Sound", "Wigmore Hall"],
};
const EXAMPLES_MOCK: Record<DomainKey, string[]> = {
  movie: ["Dancing on the Pier", "Iron Front", "Harbour Lights", "Midnight in the Cellar", "Letters to Lagos"],
  artist: ["The Jivetones", "Grindcore Unit", "Mahalia Grace Choir", "Buck Hollis"],
  tv_show: ["Seaside Detectives", "The Garden Hour"],
  place: ["The Bandstand Ballroom", "Club Neon", "Sampletown Botanical Garden"],
};

export function CheckPage() {
  const { residents, home } = useHome();
  const list = residents || [];
  const initial = new URLSearchParams(location.search).get("r");
  const [rid, setRid] = useState<string>(initial && list.some((r) => r.resident_id === initial) ? initial : list[0]?.resident_id || "");
  const [domain, setDomain] = useState<DomainKey>("movie");
  const [text, setText] = useState("");
  const [results, setResults] = useState<CheckResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const person = list.find((r) => r.resident_id === rid);
  const lines = useMemo(() => text.split(/\n|,(?=\s*[A-Z0-9"'])/).map((s) => s.replace(/^\s*(\d+[.)]|[-*•])\s*/, "").trim()).filter(Boolean).slice(0, 25), [text]);
  const examples = (home?.mock ? EXAMPLES_MOCK : EXAMPLES_LIVE)[domain];

  async function run(items = lines) {
    if (!rid || !items.length) return;
    setLoading(true);
    setErr(null);
    setOpen(null);
    try {
      const rep = await api.verify(rid, items.map((name) => ({ name, domain })));
      setResults(rep.results);
    } catch (e) { setErr(e); } finally { setLoading(false); }
  }

  async function confirm(i: number, e: Entity) {
    if (!results) return;
    try {
      const rep = await api.verify(rid, [{ name: e.name, domain, entity_id: e.id }]);
      const next = [...results];
      next[i] = rep.results[0];
      setResults(next);
      setOpen(i);
    } catch (er) { setErr(er); }
  }

  function applySwap(i: number, e: Entity) {
    const next = [...lines];
    next[i] = e.name;
    setText(next.join("\n"));
    run(next);
  }

  const counts = results?.reduce<Record<string, number>>((a, r) => ({ ...a, [r.verdict]: (a[r.verdict] || 0) + 1 }), {});

  if (!list.length) return <main className="page"><Empty title="Add a resident first" action={<Link className="btn" to="/setup">Meet a resident</Link>}>The taste check compares ideas with one person's confirmed favourites.</Empty></main>;

  return (
    <main className="page">
      <section className="page-head">
        <div>
          <span className="eyebrow">Taste check</span>
          <h1 className="display">Is this list right for them?</h1>
          <p className="lede lede--sm">Paste ideas from anyone (a colleague, a relative or an AI assistant). Hearth checks each one against the resident's favourites in Qloo's taste graph and shows its evidence.</p>
        </div>
      </section>

      <div className="check-layout">
        <section className="check-form" aria-label="List to check">
          <fieldset className="pickset">
            <legend><span className="step-num">1</span>For whom?</legend>
            <div className="pickers pickers--row">
              {list.map((r) => (
                <button key={r.resident_id} className={"picker picker--sm" + (rid === r.resident_id ? " is-on" : "")} aria-pressed={rid === r.resident_id} onClick={() => { setRid(r.resident_id); setResults(null); }}>
                  <Collage profile={r} max={2} />
                  <span className="picker__name">{r.name}</span>
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="pickset">
            <legend><span className="step-num">2</span>What kind of ideas?</legend>
            <div className="segmented" role="radiogroup">
              {DOMAINS.map((d) => (
                <button key={d.key} role="radio" aria-checked={domain === d.key} className={domain === d.key ? "is-on" : ""} onClick={() => { setDomain(d.key); setResults(null); }}>
                  <Icon name={d.icon} size={20} />{d.label}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="pickset">
            <legend><span className="step-num">3</span>The list</legend>
            <label className="sr-only" htmlFor="check-list">One idea per line</label>
            <textarea id="check-list" className="ledger" rows={7} value={text} onChange={(e) => setText(e.target.value)}
              placeholder={"One idea per line, for example:\n" + examples.slice(0, 3).join("\n")} />
            <div className="check-form__row">
              <button className="btn btn--ghost btn--sm" onClick={() => { setText(examples.join("\n")); setResults(null); }}>
                <Icon name="sparkle" size={18} />Fill with an example list
              </button>
              <span className="muted small">{lines.length}/25 ideas</span>
            </div>
          </fieldset>
          <button className="btn btn--accent btn--lg btn--block" onClick={() => run()} disabled={!lines.length || loading}>
            <Icon name="check" />{loading ? "Checking…" : `Check ${lines.length || ""} idea${lines.length === 1 ? "" : "s"} for ${person?.name ?? "them"}`}
          </button>
        </section>

        <section className="check-results" aria-live="polite" aria-label="Results">
          {loading && <Loading label={`Finding each idea in Qloo and comparing it with ${person?.name}'s favourites…`} rows={4} />}
          {err != null && <ErrorNote error={err} retry={() => run()} />}
          {!loading && !results && (
            <div className="check-empty">
              <span className="stamp stamp--weak stamp--lg" aria-hidden><span className="stamp__inner">Awaiting list</span></span>
              <p>Results appear here as stamped index cards: <strong>Good fit</strong>, <strong>Weak fit</strong>, <strong>Poor fit</strong>, <strong>Can't verify</strong> or <strong>Confirm which one</strong>, each with Qloo's evidence and a better swap where there is one.</p>
            </div>
          )}
          {results && counts && (
            <>
              <p className="tally">
                {(["good", "weak", "poor", "needs_confirmation", "cannot_verify"] as const).filter((v) => counts[v]).map((v) => (
                  <span key={v} className={`tally__item tally__item--${v}`}><span className={`dot dot--${v}`} />{counts[v]} {VERDICT[v].label.toLowerCase()}</span>
                ))}
              </p>
              <ol className="ledger-results">
                {results.map((r, i) => {
                  const ent = r.resolution.entity;
                  const isOpen = open === i;
                  return (
                    <li key={i} className={`check-card check-card--${r.verdict}`}>
                      <div className="check-card__main">
                        <span className="check-card__num">{i + 1}</span>
                        {ent ? <Photo entity={ent} size={64} shape="square" /> : <span className="photo photo--square photo--blank" style={{ width: 64, height: 64 }} aria-hidden>?</span>}
                        <div className="check-card__text">
                          <h3>{ent?.name || r.candidate.name}{ent && yearOf(ent) ? <span className="muted"> ({yearOf(ent)})</span> : null}</h3>
                          {ent && ent.name.toLowerCase() !== r.candidate.name.toLowerCase() && <span className="small muted">You wrote “{r.candidate.name}”</span>}
                          {r.verdict === "cannot_verify" && <span className="small">{sentence(r.resolution.reason)}. Hearth won't guess.</span>}
                          {r.verdict === "needs_confirmation" && <span className="small">{sentence(r.resolution.reason)}.</span>}
                        </div>
                        <Stamp verdict={r.verdict} />
                      </div>

                      {r.verdict === "needs_confirmation" && (
                        <div className="confirm-options">
                          {r.resolution.options.slice(0, 4).map((o) => (
                            <button key={o.id} className="option" onClick={() => confirm(i, o)}>
                              <Photo entity={o} size={72} shape="card" />
                              <span><strong>{o.name}</strong><span className="muted">{[...new Set([yearOf(o), o.properties?.disambiguation].filter((x) => x && String(x).toLowerCase() !== o.name.toLowerCase()).map(String))].join(" · ") || "No year listed"}</span></span>
                              <span className="option__cta">This one</span>
                            </button>
                          ))}
                        </div>
                      )}

                      {(r.verdict === "good" || r.verdict === "weak" || r.verdict === "poor") && (
                        <>
                          {r.swap && <SwapLine check={r} onUse={(e) => applySwap(i, e)} />}
                          <button className="linkbtn" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : i)}>
                            <Icon name="info" size={18} />{isOpen ? "Hide evidence" : "Show evidence"}
                          </button>
                          {isOpen && <EvidenceBlock check={r} residentName={person?.name || "them"} />}
                        </>
                      )}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      </div>

      <section className="compare-soon" aria-labelledby="soon-title">
        <span className="stamp stamp--soon stamp--md" aria-hidden><span className="stamp__inner">Coming soon</span></span>
        <h2 id="soon-title" className="display display--md">Without Qloo vs with Qloo</h2>
        <p>Ask a language model for ideas, then see its plain answer beside Hearth's checked version: same question, same model, every claim stamped. We haven't chosen the model yet, so this stays empty rather than faked.</p>
        <div className="compare-soon__cols" aria-hidden>
          <div className="compare-soon__col"><span className="eyebrow">Without Qloo</span><i /><i /><i /><i /></div>
          <div className="compare-soon__col"><span className="eyebrow">With Qloo (Hearth)</span><i /><i /><i /><i /></div>
        </div>
      </section>
    </main>
  );
}
