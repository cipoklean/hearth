import { api } from "../api";
import { useAsync } from "../state";
import { Icon } from "./Icon";
import { ErrorNote, Loading, Photo, Source } from "./ui";

export function PlaylistPanel({ id, name }: { id: string; name: string }) {
  const pl = useAsync(() => api.playlist(id), [id]);
  return (
    <section className="panel panel--playlist">
      <h2 className="panel__title"><Icon name="note" size={20} /> {name}'s playlist</h2>
      <p className="small muted">Their favourites first, then artists Qloo ranks highest for {name}'s whole taste, each with the reason. Use it for 1:1 time, music sessions or a calm evening.</p>
      {pl.loading && <Loading label="Asking Qloo which artists fit…" rows={3} />}
      {pl.error != null && <ErrorNote error={pl.error} retry={pl.reload} />}
      {pl.data && (
        <ol className="playlist-list">
          {pl.data.items.map((it) => (
            <li key={it.entity.id}>
              <Photo entity={it.entity} size={44} shape="square" />
              <span className="playlist-list__text">
                <strong>{it.entity.name}</strong>
                <span className="small muted">{it.source === "favourite" ? "A favourite" : it.reason}</span>
              </span>
              {it.source === "qloo" ? <Source kind="qloo" /> : <span className="theme-tag">Favourite</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
