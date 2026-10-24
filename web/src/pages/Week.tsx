import { useState } from "react";
import { api, type PlanItem, type Profile, type WeeklyPlan } from "../api";
import { Icon } from "../components/Icon";
import { EvidenceBlock, ErrorNote, Loading, Photo, Source, Stamp, useToast } from "../components/ui";
import { DAYS, displayTags, favourites, kindOf, leadFavourite, needInfo, SLOT, VERDICT, yearOf } from "../lib";
import { usePlan } from "../plan";
import { Link } from "../router";
import { useAsync, useHome } from "../state";

const QUIET: Record<string, { title: string; body: string; icon: string }> = {
  Friday: { title: "Family & visitors", body: "Kept free for visits. Share this week's plan with family so they can join in.", icon: "people" },
  Sunday: { title: "Rest & reminiscence", body: "A gentle day. Play a few of their favourites from the playlist.", icon: "tea" },
};

function oneLiner(it: PlanItem): string | null {
  const lead = leadFavourite(it.check);
  if (lead) return `Linked to ${lead.name}`;
  const tags = it.check?.evidence?.shared_tags?.length ? displayTags(it.check.evidence.shared_tags, 2) : [];
  if (tags.length) return `Shares ${tags.join(", ")}`;
  if (it.notes.some((n) => n.startsWith("a known favourite"))) return "One of their favourites";
  return null;
}

export function WeekPage({ id }: { id: string }) {
  const prof = useAsync(() => api.resident(id), [id]);
  const { plan, loading, error, reload, swap, resetSwaps, busySlot, setBusySlot, swapped } = usePlan(id);
  const { home } = useHome();
  const toast = useToast();
  const [open, setOpen] = useState<string | null>(null);
  const p = prof.data;

  async function doSwap(it: PlanItem) {
    const before = it.title;
    const np = await swap(it.day + it.slot, it.entity?.id, it.slot === "meal_theme" ? it.cuisine : null);
    const after = np?.items.find((x) => x.day === it.day && x.slot === it.slot)?.title;
    if (after) toast(after === before ? `No other option passes ${p?.name}'s care rules right now.` : `Swapped ${before} for ${after}.`);
  }

  async function feedback(it: PlanItem, enjoyed: boolean) {
    if (!it.entity || !p) return;
    setBusySlot(it.day + it.slot);
    try {
      await api.feedback(id, it.entity, enjoyed);
      const np = await reload(true);
      const now = np?.items.find((x) => x.day === it.day && x.slot === it.slot);
      toast(enjoyed
        ? `Noted: ${p.name} enjoyed ${it.title}. Hearth will lean on it as a signal.`
        : `Noted: Hearth won't suggest ${it.title} to ${p.name} again${now && now.title !== it.title ? `. New pick: ${now.title}.` : "."}`);
      prof.reload();
    } catch (e) {
      toast(`Couldn't save that: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusySlot(null);
    }
  }

  if (prof.error) return <main className="page"><ErrorNote error={prof.error} retry={prof.reload} /></main>;

  const byDay = (d: string) => plan?.items.filter((i) => i.day === d) || [];

  return (
    <main className="page page--week">
      <div className="no-print">
        <Link to={`/r/${id}`} className="backlink"><Icon name="back" size={18} />{p ? `${p.name}'s taste card` : "Back"}</Link>
        <section className="page-head">
          <div>
            <span className="eyebrow">Weekly plan{home?.name ? ` · ${home.name}` : ""}</span>
            <h1 className="display">{p ? `${p.name}'s week` : "This week"}</h1>
            {p && (
              <p className="lede lede--sm">
                Picked from {p.name}'s favourites by Qloo, then checked against {p.needs.length ? p.needs.map((n) => needInfo(n).label.toLowerCase()).join(", ") : "Hearth's care rules"}.
                Tap <em>Why this?</em> for the evidence.
              </p>
            )}
          </div>
          <div className="page-head__actions">
            {swapped() > 0 && <button className="btn btn--ghost btn--sm" onClick={resetSwaps}>Undo swaps</button>}
            <button className="btn" onClick={() => print()} disabled={!plan}><Icon name="print" />Print week, menu & playlist</button>
          </div>
        </section>

        {loading && <Loading label="Reading Qloo's taste graph and checking care rules…" rows={5} />}
        {error != null && <ErrorNote error={error} retry={() => reload()} />}

        {plan && (
          <>
            <ol className="glance" aria-label="Week at a glance">
              {DAYS.map((d) => {
                const its = byDay(d);
                return (
                  <li key={d} className={"glance__day" + (its.length ? "" : " is-quiet")}>
                    <a href={`#day-${d}`} className="glance__link">
                      <span className="glance__name">{d.slice(0, 3)}</span>
                      {its.length ? its.map((it) => (
                        <span key={it.slot} className="glance__item">
                          <Icon name={SLOT[it.slot].icon} size={18} />
                          <span className="glance__title">{it.title}</span>
                          {it.check && <span className={`dot dot--${it.check.verdict}`} title={VERDICT[it.check.verdict].label} />}
                        </span>
                      )) : <span className="glance__item glance__item--quiet">{QUIET[d]?.title}</span>}
                    </a>
                  </li>
                );
              })}
            </ol>

            <div className="days">
              {DAYS.map((d) => {
                const its = byDay(d);
                return (
                  <section key={d} id={`day-${d}`} className={"day" + (its.length ? "" : " day--quiet")} aria-label={d}>
                    <h2 className="day__name"><span>{d}</span></h2>
                    <div className="day__items">
                      {its.length === 0 && QUIET[d] && (
                        <div className="slip slip--quiet">
                          <Icon name={QUIET[d].icon} size={26} />
                          <div><strong>{QUIET[d].title}</strong><p className="muted">{QUIET[d].body}</p></div>
                        </div>
                      )}
                      {its.map((it) => {
                        const k = it.day + it.slot;
                        const isOpen = open === k;
                        const busy = busySlot === k;
                        const why = oneLiner(it);
                        return (
                          <article key={k} className={"slip" + (busy ? " is-busy" : "")} aria-busy={busy}>
                            <div className="slip__main">
                              {it.entity ? <Photo entity={it.entity} size={96} shape="card" /> : <span className="slip__plate"><Icon name={it.slot === "meal_theme" ? "plate" : SLOT[it.slot].icon} size={40} /></span>}
                              <div className="slip__text">
                                <span className="slip__slot"><Icon name={SLOT[it.slot].icon} size={16} />{SLOT[it.slot].label} · {SLOT[it.slot].time}</span>
                                <h3 className="slip__title">{it.title}{it.entity && yearOf(it.entity) ? <span className="muted"> ({yearOf(it.entity)})</span> : null}</h3>
                                {why && <p className="slip__why">{why}</p>}
                                {it.slot === "meal_theme" && it.dishes.length > 0 && (
                                  <ul className="dishes">{it.dishes.map((dd) => <li key={dd.name}>{dd.name}</li>)}</ul>
                                )}
                                {it.entity?.properties?.address && kindOf(it.entity.type) === "place" && <p className="small muted">{it.entity.properties.address}</p>}
                              </div>
                              <div className="slip__stamp">
                                {it.check ? <Stamp verdict={it.check.verdict} /> : it.slot === "meal_theme" && it.dishes.length ? <span className="theme-tag">Theme</span> : null}
                              </div>
                            </div>
                            <div className="slip__actions">
                              <button className="btn btn--ghost btn--sm" aria-expanded={isOpen} aria-controls={`ev-${k}`} onClick={() => setOpen(isOpen ? null : k)}>
                                <Icon name="info" size={18} />{isOpen ? "Hide why" : "Why this?"}
                              </button>
                              <button className="btn btn--ghost btn--sm" onClick={() => doSwap(it)} disabled={busy || (!it.entity && !it.cuisine)}>
                                <Icon name="swap" size={18} />Swap
                              </button>
                              {it.entity && (
                                <span className="feedback" role="group" aria-label={`How did ${p?.name ?? "they"} find ${it.title}?`}>
                                  <button className="btn btn--yes btn--sm" onClick={() => feedback(it, true)} disabled={busy}><Icon name="thumbUp" size={18} />Enjoyed</button>
                                  <button className="btn btn--no btn--sm" onClick={() => feedback(it, false)} disabled={busy}><Icon name="thumbDown" size={18} />Didn't enjoy</button>
                                </span>
                              )}
                            </div>
                            {isOpen && (
                              <div className="slip__evidence" id={`ev-${k}`}>
                                {it.slot === "meal_theme" ? (
                                  <MealEvidence it={it} name={p?.name || ""} />
                                ) : (
                                  <EvidenceBlock check={it.check} rules={it.rules} residentName={p?.name || "them"} />
                                )}
                              </div>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
            <p className="small muted center">Picks, stamps and evidence: Qloo taste. Care checks, the menu library and the schedule: Hearth.</p>
          </>
        )}
      </div>

      {plan && p && <PrintSheets plan={plan} profile={p} homeName={home?.name || ""} />}
    </main>
  );
}

function MealEvidence({ it, name }: { it: PlanItem; name: string }) {
  return (
    <div className="evidence">
      <div className="evidence__group">
        <Source kind="qloo" />
        <ul className="evidence__list">
          {it.evidence_places.length
            ? <li>Theme taken from the places Qloo ranks highest for {name}, such as <strong>{it.evidence_places.join(", ")}</strong>.</li>
            : <li className="muted">No Qloo cuisine signal for this slot; the kitchen chooses.</li>}
        </ul>
      </div>
      <div className="evidence__group">
        <Source kind="rule" />
        <ul className="evidence__list">
          <li>Dishes come from Hearth's menu library and are filtered for {name}'s food needs. A dietitian should review the library before real use.</li>
        </ul>
      </div>
    </div>
  );
}

/* Print-only: weekly schedule, menu card and playlist on A4. */
function PrintSheets({ plan, profile, homeName }: { plan: WeeklyPlan; profile: Profile; homeName: string }) {
  const meals = plan.items.filter((i) => i.slot === "meal_theme" && i.dishes.length);
  const session = plan.items.find((i) => i.slot === "music_session" && i.entity);
  const artists = favourites(profile).filter((e) => kindOf(e.type) === "artist");
  const foodNeeds = profile.needs.filter((n) => ["soft_food", "low_salt", "low_sugar", "vegetarian"].includes(n));
  return (
    <div className="print-only">
      <section className="sheet">
        <header className="sheet__head">
          <span className="sheet__brand">Hearth · {homeName}</span>
          <h1>{profile.name}'s week</h1>
          {profile.needs.length > 0 && <p>Care needs: {profile.needs.map((n) => needInfo(n).label).join(" · ")}</p>}
        </header>
        <table className="sheet__table">
          <thead><tr><th>Day</th><th>Time</th><th>Activity</th><th>Fit</th><th>Notes for staff</th></tr></thead>
          <tbody>
            {DAYS.map((d) => {
              const its = plan.items.filter((i) => i.day === d);
              if (!its.length) return <tr key={d}><td>{d}</td><td></td><td colSpan={3} className="muted">{QUIET[d]?.title}</td></tr>;
              return its.map((it, j) => (
                <tr key={d + it.slot}>
                  <td>{j === 0 ? d : ""}</td>
                  <td>{SLOT[it.slot].time}</td>
                  <td><strong>{SLOT[it.slot].label}:</strong> {it.title}</td>
                  <td>{it.check ? VERDICT[it.check.verdict].label : "Theme"}</td>
                  <td>{it.rules.filter((r) => r.outcome !== "pass").map((r) => `${needInfo(r.need).label}: ${r.reason.replace(/; staff to confirm$/, "")}`).join("; ")}</td>
                </tr>
              ));
            })}
          </tbody>
        </table>
        <p className="sheet__foot">Fit stamps come from Qloo's taste graph. Care notes are Hearth care rules. Mark enjoyed / didn't enjoy in Hearth after each activity.</p>
      </section>

      <section className="sheet sheet--menu">
        <header className="sheet__head sheet__head--center">
          <span className="sheet__brand">{homeName} · Menu card</span>
          <h1>Lunch this week</h1>
          <p>Prepared for {profile.name}{foodNeeds.length ? ` · ${foodNeeds.map((n) => needInfo(n).label.toLowerCase()).join(", ")}` : ""}</p>
        </header>
        {meals.length ? meals.map((m) => (
          <div key={m.day} className="menu-course">
            <h2>{m.day} · {m.title}</h2>
            <ul>{m.dishes.map((d) => <li key={d.name}>{d.name}</li>)}</ul>
          </div>
        )) : <p className="center">Kitchen's choice this week.</p>}
        <p className="sheet__foot center">Dishes filtered by Hearth care rules. Please check with the kitchen for allergens.</p>
      </section>

      <section className="sheet sheet--playlist">
        <header className="sheet__head">
          <span className="sheet__brand">{homeName} · Playlist</span>
          <h1>Music for {profile.name}</h1>
          {session && <p>Tuesday music session: <strong>{session.title}</strong>{session.check ? ` (${VERDICT[session.check.verdict].label.toLowerCase()})` : ""}</p>}
        </header>
        <ol className="playlist">
          {session?.entity && <li><strong>{session.entity.name}</strong> <span>session pick · Qloo</span></li>}
          {artists.map((a) => <li key={a.id}><strong>{a.name}</strong> <span>a favourite</span></li>)}
        </ol>
        <p className="sheet__foot">Play at a comfortable volume{profile.needs.includes("hearing_support") ? " and use the hearing loop" : ""}.</p>
      </section>
    </div>
  );
}
