import type { Entity, PlanItem, Profile } from "../api";
import { favourites, kindOf, tasteLine } from "../lib";
import { Icon } from "./Icon";

// Conversation starters any carer can use, built from the resident's favourites (Hearth wording)
// and Qloo's picks for them. Made for weekends and agency staff who don't know the resident yet.
function starter(e: Entity): string {
  switch (kindOf(e.type)) {
    case "artist": return `Play ${e.name} and ask where they first heard them, and who they danced with.`;
    case "movie": return `Ask about ${e.name}: where they saw it, and who went with them.`;
    case "tv_show": return `Ask what evenings were like when ${e.name} was on.`;
    case "book": return `Read a page of ${e.name} together and ask what it reminds them of.`;
    case "place": case "destination": return `Ask what they remember about ${e.name}.`;
    default: return `Ask them about ${e.name}.`;
  }
}

export function TalkCard({ profile, picks }: { profile: Profile; picks: PlanItem[] }) {
  const favs = favourites(profile).slice(0, 5);
  const line = tasteLine(profile, 4);
  const fresh = picks.filter((p) => p.entity && p.check?.verdict === "good" && !favs.some((f) => f.id === p.entity!.id)).slice(0, 3);
  return (
    <section className="talk-card" aria-labelledby="talk-title">
      <span className="eyebrow">For any carer · weekends, agency and new staff</span>
      <h2 id="talk-title" className="display display--md">Talk to {profile.name} about…</h2>
      {line && <p className="talk-card__line">{line}</p>}
      {favs.length > 0 ? (
        <ul className="talk-card__list">
          {favs.map((f) => <li key={f.id}><Icon name="heart" size={16} /> {starter(f)}</li>)}
        </ul>
      ) : <p className="muted">Add a few favourites and Hearth will write conversation starters here.</p>}
      {fresh.length > 0 && (
        <>
          <h3 className="talk-card__sub">New this week, picked by Qloo for {profile.name}</h3>
          <ul className="talk-card__list talk-card__list--plain">
            {fresh.map((p) => <li key={p.day + p.slot}><strong>{p.title}</strong> <span className="muted">· {p.day}</span></li>)}
          </ul>
        </>
      )}
      {profile.needs.length > 0 && <p className="small muted"><Icon name="shield" size={14} /> Check the care needs on {profile.name}'s card before food or outings.</p>}
    </section>
  );
}
