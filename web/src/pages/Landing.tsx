import { useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { ErrorNote } from "../components/ui";
import { Link, navigate } from "../router";
import { useHome } from "../state";

export function Landing() {
  const { residents, home, refresh } = useHome();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const hasHome = !!residents?.length;

  async function explore() {
    setBusy(true);
    setErr(null);
    try {
      if (!hasHome || !home?.demo) await api.seedDemo();
      await refresh();
      navigate("/");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="landing">
      <div className="landing__inner">
        <header className="landing__brand">
          <span className="wordmark wordmark--lg"><span className="wordmark__flame" aria-hidden><Icon name="flame" size={34} /></span><span className="wordmark__text">Hearth</span></span>
          <span className="landing__kicker">Care planning, by taste</span>
        </header>

        <section className="landing__hero">
          <div className="landing__copy">
            <h1 className="display display--hero">
              A week of meals, music, films and outings, built from what <em>each resident</em> actually loves.
            </h1>
            <p className="lede">
              Hearth checks every pick against Qloo's taste graph, shows you why it fits, and keeps care needs like soft food or step-free access in view.
            </p>

            <div className="paths">
              <button className="path path--primary" onClick={explore} disabled={busy} aria-describedby="path-demo-desc">
                <span className="path__eyebrow">{busy ? "Setting the table…" : "Take a look first"}</span>
                <span className="path__title">Explore a sample care home</span>
                <span className="path__desc" id="path-demo-desc">Maple House: four residents with their own tastes and care needs. Ready in seconds.</span>
                <span className="path__go" aria-hidden>{busy ? <span className="spinner" /> : <Icon name="arrow" size={26} />}</span>
              </button>
              <Link to="/setup" className="path" aria-describedby="path-setup-desc">
                <span className="path__eyebrow">Start with your own</span>
                <span className="path__title">Set up your own</span>
                <span className="path__desc" id="path-setup-desc">Meet your first resident in three short steps: name, favourites, care needs.</span>
                <span className="path__go" aria-hidden><Icon name="arrow" size={26} /></span>
              </Link>
            </div>
            {err != null && <ErrorNote error={err} retry={explore} />}
            {hasHome && <p className="landing__return"><Link to="/">Back to {home?.name || "your residents"} →</Link></p>}
          </div>

          <div className="landing__art" aria-hidden>
            <span className="art-caption">An example of what you'll see</span>
            <div className="art-card art-card--taste">
              <span className="art-card__tab">Taste card</span>
              <span className="art-card__name">Rose</span>
              <span className="art-card__line">Swing · Jazz · Classic film</span>
              <span className="art-card__chips"><i /><i /><i /><i /></span>
              <span className="art-needs"><b>Soft food</b><b>Gentle films</b></span>
            </div>
            <div className="art-card art-card--slip">
              <span className="art-slip__day">Thursday · Film night</span>
              <span className="art-slip__title">An evening with a 1950s romance</span>
              <span className="art-slip__why">Qloo links this most to <b>Roman Holiday</b></span>
              <span className="stamp stamp--good stamp--md art-stamp"><span className="stamp__inner">Good fit</span></span>
            </div>
            <div className="art-card art-card--menu">
              <span className="art-menu__head">Lunch · Afternoon tea</span>
              <span>Finger sandwiches, crusts off</span>
              <span>Egg custard</span>
              <span className="art-menu__rule"><Icon name="shield" size={14} /> Hearth care rule: soft food</span>
            </div>
          </div>
        </section>

        <section className="how" aria-label="How Hearth works">
          <ol className="how__list">
            <li className="how__card"><span className="how__num">1</span><h2>Tell us their favourites</h2><p>Tap to choose the singers, films and places they love. No forms full of medical detail.</p></li>
            <li className="how__card"><span className="how__num">2</span><h2>Get a week that fits</h2><p>Lunch themes, a music session, film night and an outing, each stamped with how well it fits and why.</p></li>
            <li className="how__card"><span className="how__num">3</span><h2>Check anyone's ideas</h2><p>Paste a list from a colleague, a relative or an AI. Hearth verifies each one and suggests better swaps.</p></li>
          </ol>
          <p className="how__foot"><span className="source source--qloo"><span className="source__dot" />Qloo taste</span> tells us what someone is likely to enjoy. <span className="source source--rule"><Icon name="shield" size={14} />Hearth care rule</span> keeps their needs safe. You always see which is which.</p>
        </section>
      </div>
    </main>
  );
}
