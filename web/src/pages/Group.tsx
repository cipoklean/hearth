import { useState } from "react";
import { api, type GroupPick } from "../api";
import { Icon } from "../components/Icon";
import { Collage, Empty, ErrorNote, Loading, Photo, Source, Stamp } from "../components/ui";
import { displayTags, pct, yearOf } from "../lib";
import { Link } from "../router";
import { useHome } from "../state";

const ACTIVITIES = [
  { key: "movie", label: "Film night", icon: "film", noun: "film" },
  { key: "artist", label: "Music session", icon: "note", noun: "artist" },
  { key: "place", label: "Outing", icon: "pin", noun: "place" },
  { key: "tv_show", label: "TV afternoon", icon: "tv", noun: "programme" },
];

export function GroupPage() {
  const { residents } = useHome();
  const list = residents || [];
  const [sel, setSel] = useState<string[]>(() => list.map((r) => r.resident_id));
  const [domain, setDomain] = useState("movie");
  const [res, setRes] = useState<GroupPick | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const act = ACTIVITIES.find((a) => a.key === domain)!;
  const nameOf = (id: string | null) => list.find((r) => r.resident_id === id)?.name || "";

  async function run() {
    setLoading(true);
    setErr(null);
    setRes(null);
    try { setRes(await api.groupPick(sel, domain)); } catch (e) { setErr(e); } finally { setLoading(false); }
  }

  if (!list.length) return <main className="page"><Empty title="No residents yet" action={<Link className="btn" to="/setup">Meet a resident</Link>} /></main>;

  return (
    <main className="page">
      <section className="page-head">
        <div>
          <span className="eyebrow">Group activity</span>
          <h1 className="display">One activity that suits the most people</h1>
          <p className="lede lede--sm">Choose who's joining and what kind of activity. Hearth finds the best shared fit, names anyone it would leave out, and offers them an alternative.</p>
        </div>
      </section>

      <section className="group-form">
        <fieldset className="pickset">
          <legend><span className="step-num">1</span>Who's joining? <span className="muted">({sel.length} chosen)</span></legend>
          <div className="pickers">
            {list.map((r) => {
              const on = sel.includes(r.resident_id);
              return (
                <button key={r.resident_id} className={"picker" + (on ? " is-on" : "")} aria-pressed={on}
                  onClick={() => setSel(on ? sel.filter((x) => x !== r.resident_id) : [...sel, r.resident_id])}>
                  <Collage profile={r} max={3} />
                  <span className="picker__name">{r.name}</span>
                  <span className="picker__tick" aria-hidden>{on ? <Icon name="check" size={18} /> : <Icon name="plus" size={18} />}</span>
                </button>
              );
            })}
          </div>
        </fieldset>
        <fieldset className="pickset">
          <legend><span className="step-num">2</span>What kind of activity?</legend>
          <div className="segmented segmented--big" role="radiogroup">
            {ACTIVITIES.map((a) => (
              <button key={a.key} role="radio" aria-checked={domain === a.key} className={domain === a.key ? "is-on" : ""} onClick={() => setDomain(a.key)}>
                <Icon name={a.icon} size={22} />{a.label}
              </button>
            ))}
          </div>
        </fieldset>
        <button className="btn btn--accent btn--lg" onClick={run} disabled={!sel.length || loading}>
          <Icon name="sparkle" />{loading ? "Finding the best fit…" : `Find the best ${act.noun} for ${sel.length} ${sel.length === 1 ? "person" : "people"}`}
        </button>
      </section>

      {loading && <Loading label={`Asking Qloo how each of ${sel.length} residents would feel about each option…`} rows={4} />}
      {err != null && <ErrorNote error={err} retry={run} />}

      {res && (
        <section className="group-result" aria-live="polite">
          {!res.pick ? (
            <Empty title="No option passed everyone's care rules">
              Hearth looked at {res.considered} options. Try fewer people, or another kind of activity.
            </Empty>
          ) : (
            <>
              <div className="pick-card">
                <Photo entity={res.pick} size={170} shape="card" />
                <div className="pick-card__text">
                  <span className="eyebrow">Best shared {act.noun}</span>
                  <h2 className="display">{res.pick.name}{yearOf(res.pick) ? <span className="muted"> ({yearOf(res.pick)})</span> : null}</h2>
                  <p className="pick-card__sum">
                    Suits <strong>{res.fits.filter((f) => f.verdict !== "poor").length} of {res.fits.length}</strong> residents · chosen from {res.considered} options Qloo ranked for this group.
                  </p>
                  {displayTags(res.pick.tags, 4).length > 0 && <p className="tags">{displayTags(res.pick.tags, 4).map((t) => <span key={t} className="tag">{t}</span>)}</p>}
                  <Source kind="qloo" />
                </div>
              </div>

              <h3 className="section-title">How it fits each person</h3>
              <ul className="fit-rows">
                {res.fits.map((f) => {
                  const r = list.find((x) => x.resident_id === f.resident_id);
                  const lo = res.left_out.find((l) => l.resident_id === f.resident_id);
                  return (
                    <li key={f.resident_id} className={"fit-row" + (lo ? " is-left" : "")}>
                      {r && <Collage profile={r} max={2} />}
                      <div className="fit-row__who">
                        <strong>{f.name}</strong>
                        <span className="muted">{f.verdict === "good" ? `Loves this kind of thing · fit ${pct(f.relative_fit)}` : f.verdict === "weak" ? `Should be fine · fit ${pct(f.relative_fit)}` : `Likely left out · Qloo scores this low for ${f.name}`}</span>
                        {f.shared_tags.length > 0 && <span className="small">Shares {displayTags(f.shared_tags, 3).join(", ")}</span>}
                      </div>
                      <Stamp verdict={f.verdict} size="sm" />
                      {lo && (
                        <div className="fit-row__alt">
                          {lo.alternative ? (
                            <>
                              <Photo entity={lo.alternative} size={48} shape="square" />
                              <span><span className="eyebrow">Alternative for {f.name}</span><strong>{lo.alternative.name}</strong> <span className="muted">· 1:1 or small group · fit {pct(lo.alternative_fit)}</span></span>
                            </>
                          ) : (
                            <span className="muted">No alternative in Qloo's top picks for {f.name} passes their care rules. Staff to choose.</span>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>

              {res.excluded.length > 0 && (
                <details className="excluded">
                  <summary><Icon name="shield" size={18} />{res.excluded.length} option{res.excluded.length === 1 ? "" : "s"} set aside by care rules</summary>
                  <p className="small muted">These might fit people's taste, but break someone's care need. <Source kind="rule" /></p>
                  <ul>
                    {res.excluded.map((x) => (
                      <li key={x.entity.id}>
                        <Photo entity={x.entity} size={40} shape="square" />
                        <span><strong>{x.entity.name}</strong><span className="muted"> · {x.reason.replace(/ \(Hearth rule, not Qloo\)$/, "")}</span></span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {sel.length > 0 && <p className="small muted">Planned for {sel.map(nameOf).join(", ")}.</p>}
            </>
          )}
        </section>
      )}
    </main>
  );
}
