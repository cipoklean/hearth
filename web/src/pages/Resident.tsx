import { useState } from "react";
import { api, type EraSetting } from "../api";
import { Icon } from "../components/Icon";
import { Collage, Empty, EraPicker, ErrorNote, Loading, NeedBadge, Photo, Source, Stamp, useToast } from "../components/ui";
import { autoEra, DOMAINS, favourites, kindOf, needInfo, SLOT, tasteLine, yearOf } from "../lib";
import { usePlan } from "../plan";
import { Link } from "../router";
import { useAsync } from "../state";

export function ResidentPage({ id }: { id: string }) {
  const prof = useAsync(() => api.resident(id), [id]);
  const hist = useAsync(() => api.history(id), [id]);
  const { plan, loading, error, reload } = usePlan(id);
  const [savingEra, setSavingEra] = useState(false);
  const toast = useToast();

  async function saveEra(v: EraSetting) {
    setSavingEra(true);
    try {
      const np = await api.setEra(id, v);
      prof.reload();
      await reload(true);
      toast(np.era ? `Film nights for ${np.name} now stay up to ${np.era.max_year}.` : `No era limit for ${np.name}'s films.`);
    } catch (e) {
      toast(`Couldn't save that: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSavingEra(false);
    }
  }

  if (prof.error) return <main className="page"><ErrorNote error={prof.error} retry={prof.reload} /><Link to="/">Back to residents</Link></main>;
  if (!prof.data) return <main className="page"><Loading label="Fetching their taste card…" /></main>;
  const p = prof.data;
  const favs = favourites(p);
  const line = tasteLine(p, 4);

  return (
    <main className="page">
      <Link to="/" className="backlink"><Icon name="back" size={18} />All residents</Link>

      <section className="profile-head">
        <div className="profile-head__card">
          <Collage profile={p} max={6} />
        </div>
        <div className="profile-head__text">
          <span className="eyebrow">Taste card</span>
          <h1 className="display display--xl">{p.name}</h1>
          {line && <p className="profile-head__line">{line}</p>}
          <div className="profile-head__actions">
            <Link to={`/r/${id}/week`} className="btn btn--accent" data-tour="week"><Icon name="calendar" />Open {p.name}'s week</Link>
            <Link to={`/check?r=${id}`} className="btn btn--ghost"><Icon name="list" />Check ideas for {p.name}</Link>
          </div>
        </div>
      </section>

      <div className="profile-grid">
        <section className="panel">
          <h2 className="panel__title">Favourites <span className="panel__count">{favs.length}</span></h2>
          {favs.length === 0 ? (
            <Empty title="No favourites yet">Hearth reads taste from favourites. Remove and re-add {p.name} with a few songs or films to start planning.</Empty>
          ) : (
            DOMAINS.filter((d) => favs.some((f) => kindOf(f.type) === d.key)).map((d) => (
              <div key={d.key} className="fav-group">
                <h3 className="fav-group__title"><Icon name={d.icon} size={18} />{d.label}</h3>
                <ul className="fav-list">
                  {favs.filter((f) => kindOf(f.type) === d.key).map((f) => (
                    <li key={f.id}><Photo entity={f} size={52} shape="square" /><span>{f.name}{yearOf(f) ? <span className="muted"> ({yearOf(f)})</span> : null}</span></li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>

        <section className="panel">
          <h2 className="panel__title">Care needs</h2>
          {p.needs.length === 0 ? <p className="muted">None recorded.</p> : (
            <ul className="need-list">
              {p.needs.map((n) => <li key={n}><NeedBadge need={n} /><span className="muted">{needInfo(n).hint}</span></li>)}
            </ul>
          )}
          <p className="small muted"><Icon name="shield" size={14} /> Checked by Hearth care rules, never by Qloo.</p>

          <h2 className="panel__title panel__title--spaced">Film and TV era</h2>
          <p className="small muted"><Source kind="setting" /> {p.era ? `Film nights and swaps stay up to ${p.era.max_year}${p.era.source === "auto" ? " (newest favourite film + 10 years)" : ""}.` : "No era limit: any release year."}</p>
          <EraPicker key={`${p.era_mode}-${p.era_max_year}`} value={{ era_mode: p.era_mode, era_max_year: p.era_max_year }}
            onChange={saveEra} auto={autoEra(p.entities.filter((e) => !p.disliked.includes(e.id)))} name={p.name} disabled={savingEra} />

          <h2 className="panel__title panel__title--spaced">What they enjoyed</h2>
          {hist.data && hist.data.length > 0 ? (
            <ul className="history">
              {hist.data.slice(0, 8).map((h, i) => (
                <li key={h.entity_id + i} className={h.enjoyed ? "is-yes" : "is-no"}>
                  <Icon name={h.enjoyed ? "thumbUp" : "thumbDown"} size={18} />
                  <span><strong>{h.name || "An activity"}</strong> {h.enjoyed ? "enjoyed" : "didn't enjoy"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Nothing marked yet. After an activity, tap <em>Enjoyed</em> or <em>Didn't enjoy</em> on the week plan and Hearth learns from it.</p>
          )}
        </section>

        <section className="panel panel--week">
          <h2 className="panel__title">This week</h2>
          {loading && <Loading label="Reading Qloo's taste graph…" rows={3} />}
          {error != null && <ErrorNote error={error} retry={() => reload()} />}
          {plan && (
            <ol className="mini-week">
              {plan.items.map((it) => (
                <li key={it.day + it.slot}>
                  <span className="mini-week__day">{it.day.slice(0, 3)}</span>
                  <span className="mini-week__body">
                    <span className="mini-week__slot"><Icon name={SLOT[it.slot].icon} size={16} />{SLOT[it.slot].label}</span>
                    <span className="mini-week__title">{it.title}</span>
                  </span>
                  {it.check && <Stamp verdict={it.check.verdict} size="sm" />}
                </li>
              ))}
            </ol>
          )}
          <Link to={`/r/${id}/week`} className="btn btn--ghost btn--block">See the full week, swap or print <Icon name="arrow" /></Link>
        </section>
      </div>

      <p className="small muted center"><Link to="/privacy">What Hearth stores about {p.name}, and how to remove it</Link></p>
    </main>
  );
}
