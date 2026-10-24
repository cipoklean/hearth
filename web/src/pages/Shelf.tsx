import { Icon } from "../components/Icon";
import { Tour } from "../components/Tour";
import { Empty, TasteCard } from "../components/ui";
import { Link } from "../router";
import { useHome } from "../state";

export function Shelf() {
  const { residents, home } = useHome();
  const list = residents || [];
  const first = list[0];

  return (
    <main className="page">
      <section className="page-head">
        <div>
          <span className="eyebrow">{home?.name || "Your care home"} · {list.length} resident{list.length === 1 ? "" : "s"}</span>
          <h1 className="display">Whose week are we planning?</h1>
          <p className="lede lede--sm">Open a taste card to see that person's week. Every pick carries a stamp and the reason behind it.</p>
        </div>
        <Link to="/setup" className="btn btn--accent" data-tour="add"><Icon name="plus" />Meet a resident</Link>
      </section>

      {list.length === 0 ? (
        <Empty title="No residents yet" action={<Link to="/setup" className="btn">Meet your first resident</Link>}>
          Start with one person. You can add favourites and care needs in about a minute.
        </Empty>
      ) : (
        <div className="shelf" data-tour="shelf">
          {list.map((p, i) => <TasteCard key={p.resident_id} profile={p} to={`/r/${p.resident_id}`} tourId={i === 0 ? "card" : undefined} />)}
          <Link to="/setup" className="taste-card taste-card--add">
            <span className="add-mark" aria-hidden><Icon name="plus" size={30} /></span>
            <span className="taste-card__name">Meet a resident</span>
            <span className="taste-card__line">Name, favourites, care needs. About a minute.</span>
          </Link>
        </div>
      )}

      {list.length > 0 && (
        <section className="tools" aria-label="Planning tools">
          <Link to="/group" className="tool" data-tour="group">
            <Icon name="sparkle" size={30} />
            <span className="tool__title">Plan a group activity</span>
            <span className="tool__desc">One film, outing or music session that suits the most people, with an alternative for anyone left out.</span>
          </Link>
          <Link to="/check" className="tool" data-tour="check">
            <Icon name="list" size={30} />
            <span className="tool__title">Check a list of ideas</span>
            <span className="tool__desc">Paste suggestions from anyone (a colleague, a relative or an AI) and see which ones really fit.</span>
          </Link>
        </section>
      )}

      {list.length > 0 && home?.demo && (
        <Tour
          steps={[
            { target: "card", title: "One card per resident", body: `${first?.name}'s favourite music and films, plus care needs like soft food. Tap a card to open their week.` },
            { target: "group", title: "Plan for a group", body: "Pick who's joining and Hearth finds the film or outing that suits the most people, and says who would be left out." },
            { target: "check", title: "Check anyone's ideas", body: "Paste a list from anywhere. Each idea gets a stamp (Good, Weak or Poor fit) with Qloo's evidence and a better swap." },
          ]}
        />
      )}
    </main>
  );
}
