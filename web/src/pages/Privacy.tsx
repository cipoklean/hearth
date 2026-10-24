import { useState } from "react";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Collage, useToast } from "../components/ui";
import { navigate } from "../router";
import { useHome } from "../state";

export function PrivacyPage() {
  const { residents, home, refresh } = useHome();
  const toast = useToast();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function remove(id: string, name: string) {
    setBusy(true);
    try {
      await api.deleteResident(id);
      localStorage.removeItem(`hearth.skip.${id}`);
      await refresh();
      toast(`${name} and everything Hearth stored about them has been removed.`);
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  }

  async function eraseAll() {
    setBusy(true);
    try {
      const r = await api.eraseHome();
      Object.keys(localStorage).filter((k) => k.startsWith("hearth.skip.")).forEach((k) => localStorage.removeItem(k));
      await refresh();
      toast(`Erased ${r.deleted_residents} resident${r.deleted_residents === 1 ? "" : "s"} and this home's settings.`);
      navigate("/welcome");
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  }

  return (
    <main className="page page--narrow">
      <section className="page-head">
        <div>
          <span className="eyebrow">Privacy</span>
          <h1 className="display">What Hearth keeps, and what it doesn't</h1>
          <p className="lede lede--sm">Hearth is built to know as little as possible about the people it helps.</p>
        </div>
      </section>

      <div className="privacy-cols">
        <section className="panel">
          <h2 className="panel__title"><Icon name="check" />Stored, per resident</h2>
          <ul className="plain-list">
            <li><strong>A display name</strong>: a first name or initials.</li>
            <li><strong>Confirmed favourites</strong>: the Qloo ID and name of each song, film or place you chose.</li>
            <li><strong>Care needs</strong>: the toggles you set, such as soft food or wheelchair.</li>
            <li><strong>Enjoyed / didn't enjoy</strong> marks, which change what Hearth suggests.</li>
          </ul>
        </section>
        <section className="panel">
          <h2 className="panel__title"><Icon name="cross" />Never stored</h2>
          <ul className="plain-list">
            <li>Dates of birth, room numbers, photos of residents or medical records.</li>
            <li>Free-text notes.</li>
            <li>Qloo's responses alongside a person. Pictures of favourites are fetched when you look at them.</li>
          </ul>
        </section>
      </div>
      <p className="small muted">This browser keeps its own care home, identified by a random code (no account). Care rules are guidance for staff; anything Hearth can't confirm is marked “staff to confirm”.</p>

      <section className="panel">
        <h2 className="panel__title"><Icon name="trash" />Remove a resident</h2>
        {!residents?.length ? <p className="muted">No residents stored.</p> : (
          <ul className="remove-list">
            {residents.map((r) => (
              <li key={r.resident_id}>
                <Collage profile={r} max={2} />
                <span className="remove-list__name">{r.name}<span className="muted small"> · {r.entities.length} favourites · {r.needs.length} care needs</span></span>
                {confirming === r.resident_id ? (
                  <span className="confirm-inline" role="group" aria-label={`Confirm removing ${r.name}`}>
                    <span>Remove {r.name} for good?</span>
                    <button className="btn btn--ghost btn--sm" onClick={() => setConfirming(null)}>Keep</button>
                    <button className="btn btn--danger btn--sm" onClick={() => remove(r.resident_id, r.name)} disabled={busy}>Yes, remove</button>
                  </span>
                ) : (
                  <button className="btn btn--ghost btn--sm" onClick={() => setConfirming(r.resident_id)}><Icon name="trash" size={18} />Remove</button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="erase">
          {confirming === "__all" ? (
            <span className="confirm-inline">
              <span>Erase {home?.name || "this home"} and all {residents?.length || 0} residents?</span>
              <button className="btn btn--ghost btn--sm" onClick={() => setConfirming(null)}>Cancel</button>
              <button className="btn btn--danger btn--sm" onClick={eraseAll} disabled={busy}>Erase everything</button>
            </span>
          ) : (
            <button className="btn btn--ghost btn--sm" onClick={() => setConfirming("__all")}>Erase this whole home and start again</button>
          )}
        </div>
      </section>
    </main>
  );
}
