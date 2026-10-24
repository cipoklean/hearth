import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Entity, type EraSetting, type Need, type Profile, type SearchHit } from "../api";
import { Icon } from "../components/Icon";
import { EraPicker, ErrorNote, Photo, Source, TasteCard } from "../components/ui";
import { autoEra, DOMAINS, type DomainKey, NEEDS } from "../lib";
import { Link, navigate } from "../router";
import { useHome } from "../state";

type Step = "home" | "name" | "favs" | "needs" | "done";

const hitToEntity = (h: SearchHit): Entity => ({
  id: h.id, name: h.name, type: h.type, tags: h.tags,
  properties: { image: h.image ? { url: h.image } : undefined, release_year: h.year ?? undefined },
});

export function Setup() {
  const { home, refresh } = useHome();
  const needsHome = !home?.name;
  const [step, setStep] = useState<Step>(needsHome ? "home" : "name");
  const [homeName, setHomeName] = useState("");
  const [city, setCity] = useState("");
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Entity[]>([]);
  const [needs, setNeeds] = useState<Need[]>([]);
  const [era, setEra] = useState<EraSetting>({ era_mode: "auto", era_max_year: null });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [created, setCreated] = useState<Profile | null>(null);

  const steps: { key: Step; label: string }[] = [
    ...(needsHome ? [{ key: "home" as Step, label: "Your home" }] : []),
    { key: "name", label: "Name" },
    { key: "favs", label: "Favourites" },
    { key: "needs", label: "Care needs" },
  ];
  const idx = steps.findIndex((s) => s.key === step);

  async function saveHome(skip = false) {
    if (!skip) await api.setHome(homeName.trim() || "Our home", city.trim());
    else await api.setHome("Our home", "");
    setStep("name");
  }

  async function finish() {
    setSaving(true);
    setErr(null);
    try {
      const p = await api.createResident(name.trim(), picked, needs, era);
      await refresh();
      setCreated((await api.residents()).find((r) => r.resident_id === p.resident_id) || p);
      setStep("done");
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  }

  function restart() {
    setName(""); setPicked([]); setNeeds([]); setEra({ era_mode: "auto", era_max_year: null }); setCreated(null); setStep("name");
  }

  return (
    <main className="page page--narrow setup">
      {step !== "done" && (
        <ol className="stepper" aria-label="Setup progress">
          {steps.map((s, i) => (
            <li key={s.key} className={i < idx ? "is-done" : i === idx ? "is-current" : ""} aria-current={i === idx ? "step" : undefined}>
              <span className="stepper__dot">{i < idx ? <Icon name="check" size={16} /> : i + 1}</span>
              <span className="stepper__label">{s.label}</span>
            </li>
          ))}
        </ol>
      )}

      {step === "home" && (
        <section className="card-sheet">
          <span className="eyebrow">First, your home</span>
          <h1 className="display">What's your care home called?</h1>
          <p className="lede lede--sm">The town helps Hearth suggest outings nearby. Both are optional.</p>
          <form onSubmit={(e) => { e.preventDefault(); saveHome(); }} className="form">
            <label className="field"><span>Home name</span>
              <input value={homeName} onChange={(e) => setHomeName(e.target.value)} placeholder="e.g. Rosewood Lodge" maxLength={80} autoFocus />
            </label>
            <label className="field"><span>Town or city</span>
              <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="e.g. Manchester" maxLength={80} />
            </label>
            <div className="form__actions">
              <button type="button" className="btn btn--ghost" onClick={() => saveHome(true)}>Skip for now</button>
              <button className="btn btn--accent">Continue <Icon name="arrow" /></button>
            </div>
          </form>
        </section>
      )}

      {step === "name" && (
        <section className="card-sheet">
          <span className="eyebrow">Meet a resident</span>
          <h1 className="display">Who are we getting to know?</h1>
          <p className="lede lede--sm">A first name or initials is enough. Hearth doesn't need birthdays, rooms or medical records.</p>
          <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) setStep("favs"); }} className="form">
            <label className="field field--big"><span>Their name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Rose" maxLength={80} autoFocus required />
            </label>
            <div className="form__actions">
              <span />
              <button className="btn btn--accent" disabled={!name.trim()}>Next: favourites <Icon name="arrow" /></button>
            </div>
          </form>
        </section>
      )}

      {step === "favs" && (
        <Favourites name={name} picked={picked} setPicked={setPicked}
          onBack={() => setStep("name")} onNext={() => setStep("needs")} />
      )}

      {step === "needs" && (
        <section className="card-sheet">
          <span className="eyebrow">Care needs · {name}</span>
          <h1 className="display">Anything we should take care with?</h1>
          <p className="lede lede--sm">These are checked by Hearth's own care rules, not by Qloo. Tap all that apply.</p>
          <div className="toggles" role="group" aria-label="Care needs">
            {NEEDS.map((n) => {
              const on = needs.includes(n.key);
              return (
                <button key={n.key} type="button" className={"toggle" + (on ? " is-on" : "")} aria-pressed={on}
                  onClick={() => setNeeds(on ? needs.filter((x) => x !== n.key) : [...needs, n.key])}>
                  <span className="toggle__icon"><Icon name={n.icon} size={26} /></span>
                  <span className="toggle__label">{n.label}</span>
                  <span className="toggle__hint">{n.hint}</span>
                  <span className="toggle__tick" aria-hidden>{on && <Icon name="check" size={18} />}</span>
                </button>
              );
            })}
          </div>
          <div className="era-block">
            <h2 className="panel__title">Films and TV from which years?</h2>
            <p className="muted small"><Source kind="setting" /> Hearth keeps film nights and swaps to this era, because Qloo's picks lean modern.</p>
            <EraPicker value={era} onChange={setEra} auto={autoEra(picked)} name={name} />
          </div>
          {err != null && <ErrorNote error={err} />}
          <div className="form__actions">
            <button className="btn btn--ghost" onClick={() => setStep("favs")}><Icon name="back" />Back</button>
            <button className="btn btn--accent" onClick={finish} disabled={saving}>
              {saving ? "Saving…" : needs.length ? `Save ${name}` : `None needed · save ${name}`} <Icon name="check" />
            </button>
          </div>
        </section>
      )}

      {step === "done" && created && (
        <section className="done">
          <span className="eyebrow">All set</span>
          <h1 className="display">{created.name} is on the shelf.</h1>
          <p className="lede lede--sm">
            {created.entities.length
              ? "Hearth can now plan a week around these favourites. You can add more later."
              : "No favourites yet, so Hearth can't read their taste. Add a few and the week fills itself."}
          </p>
          <div className="done__card"><TasteCard profile={created} to={`/r/${created.resident_id}`} /></div>
          <div className="form__actions form__actions--center">
            <button className="btn btn--ghost" onClick={restart}><Icon name="plus" />Meet another resident</button>
            <button className="btn btn--accent" onClick={() => navigate(`/r/${created.resident_id}/week`)} disabled={!created.entities.length}>
              See {created.name}'s week <Icon name="arrow" />
            </button>
          </div>
          <p className="center"><Link to="/">Back to all residents</Link></p>
        </section>
      )}
    </main>
  );
}

function Favourites({ name, picked, setPicked, onBack, onNext }: {
  name: string; picked: Entity[]; setPicked: (e: Entity[]) => void; onBack: () => void; onNext: () => void;
}) {
  const [domain, setDomain] = useState<DomainKey>("artist");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const seq = useRef(0);
  const d = DOMAINS.find((x) => x.key === domain)!;

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits(null); return; }
    const my = ++seq.current;
    const t = setTimeout(async () => {
      setLoading(true);
      setErr(null);
      try {
        const r = await api.search(term, domain);
        if (my === seq.current) setHits(r.results);
      } catch (e) {
        if (my === seq.current) setErr(e);
      } finally {
        if (my === seq.current) setLoading(false);
      }
    }, 450);
    return () => clearTimeout(t);
  }, [q, domain]);

  // Several results with the same name: ask staff to confirm which one.
  const sameName = useMemo(() => {
    if (!hits) return false;
    const n = q.trim().toLowerCase();
    return hits.filter((h) => h.name.toLowerCase() === n).length > 1;
  }, [hits, q]);

  const isPicked = (id: string) => picked.some((p) => p.id === id);
  const toggle = (h: SearchHit) =>
    setPicked(isPicked(h.id) ? picked.filter((p) => p.id !== h.id) : [...picked, hitToEntity(h)]);

  return (
    <section className="card-sheet card-sheet--wide">
      <span className="eyebrow">Favourites · {name}</span>
      <h1 className="display">What does {name} love?</h1>
      <p className="lede lede--sm">Type a name and tap the right one. Three or four favourites is plenty to start.</p>

      <div className="segmented" role="tablist" aria-label="Kind of favourite">
        {DOMAINS.map((x) => (
          <button key={x.key} role="tab" aria-selected={domain === x.key} className={domain === x.key ? "is-on" : ""}
            onClick={() => { setDomain(x.key); setHits(null); }}>
            <Icon name={x.icon} size={20} />{x.label}
            {picked.some((p) => p.type.endsWith(":" + x.key)) && <span className="count">{picked.filter((p) => p.type.endsWith(":" + x.key)).length}</span>}
          </button>
        ))}
      </div>

      <label className="searchbox">
        <Icon name="search" />
        <span className="sr-only">Search for a {d.noun}</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search for a ${d.noun} · ${d.example}`} autoFocus />
        {loading && <span className="spinner" aria-label="Searching" />}
      </label>

      {sameName && (
        <p className="confirm-banner"><Icon name="info" />More than one “{q.trim()}”. Check the year and picture, then tap the one {name} means.</p>
      )}
      {err != null && <ErrorNote error={err} />}

      <div className="results" aria-live="polite">
        {hits === null && !loading && (
          <p className="hint">Try a {d.noun} {name} has always enjoyed. Results come from Qloo, so you can be sure Hearth knows exactly which one you mean.</p>
        )}
        {hits && hits.length === 0 && <p className="hint">No match in Qloo for “{q}”. Try a different spelling or a fuller title.</p>}
        {hits?.map((h) => {
          const on = isPicked(h.id);
          return (
            <button key={h.id} className={"result" + (on ? " is-on" : "")} aria-pressed={on} onClick={() => toggle(h)}>
              <Photo src={h.image} name={h.name} size={120} shape="card" />
              <span className="result__name">{h.name}</span>
              <span className="result__meta">{[...new Set([h.year, h.disambiguation].filter((x) => x && String(x).toLowerCase() !== h.name.toLowerCase()).map(String))].join(" · ") || h.display_tags.slice(0, 2).join(" · ")}</span>
              {h.year && h.display_tags.length > 0 && <span className="result__tags">{h.display_tags.slice(0, 2).join(" · ")}</span>}
              <span className="result__tick" aria-hidden>{on ? <Icon name="check" size={18} /> : <Icon name="plus" size={18} />}</span>
            </button>
          );
        })}
      </div>

      <div className="tray" aria-label="Chosen favourites">
        <span className="tray__label">{picked.length ? `Chosen (${picked.length})` : "Nothing chosen yet"}</span>
        <div className="tray__chips">
          {picked.map((p) => (
            <span key={p.id} className="chip">
              <Photo entity={p} size={30} />
              {p.name}
              <button aria-label={`Remove ${p.name}`} onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}><Icon name="cross" size={14} /></button>
            </span>
          ))}
        </div>
      </div>

      <div className="form__actions">
        <button className="btn btn--ghost" onClick={onBack}><Icon name="back" />Back</button>
        <span className="form__actions-right">
          {!picked.length && <button className="btn btn--ghost" onClick={onNext}>Skip for now</button>}
          <button className="btn btn--accent" onClick={onNext} disabled={!picked.length}>Next: care needs <Icon name="arrow" /></button>
        </span>
      </div>
    </section>
  );
}
