import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { castVote, fetchBoard } from "../lib/boards.js";
import { formatAmount } from "../lib/products.js";

const REFRESH_MS = 8000;

/** The page a family member opens from the shared link: the options and a vote button each. */
export default function BoardPage({ id }) {
  const [board, setBoard] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = () =>
      fetchBoard(id).then(
        (loaded) => {
          if (!active) return;
          setBoard(loaded);
          setError("");
        },
        (loadError) => active && setError(loadError.message)
      );

    refresh();
    // Votes from other phones show up without reloading.
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id]);

  async function vote(option) {
    if (busy) return;
    setBusy(true);
    try {
      setBoard(await castVote(id, option));
      setError("");
    } catch (voteError) {
      setError(voteError.message);
    } finally {
      setBusy(false);
    }
  }

  const leader = board && board.total_votes > 0 ? Math.max(...board.votes) : null;

  return (
    <main className="board-page container">
      <a className="board-home" href="/">
        <Icon name="search" size={15} /> Vistora
      </a>

      {!board && !error && <p className="board-status">Loading…</p>}
      {error && !board && (
        <div className="alert alert-error" role="alert">
          <Icon name="alert" size={17} />
          <span>{error}</span>
        </div>
      )}

      {board && (
        <>
          <h1>{board.title}</h1>
          <p className="board-sub">
            {board.total_votes === 0
              ? "No votes yet. Be the first."
              : `${board.total_votes} vote${board.total_votes === 1 ? "" : "s"} so far. You can change yours.`}
          </p>

          <ul className="board-options">
            {board.items.map((item, index) => {
              const votes = board.votes[index];
              const share = board.total_votes ? Math.round((votes / board.total_votes) * 100) : 0;
              const mine = board.my_vote === index;
              return (
                <li key={`${item.name}-${index}`} className={`board-option ${mine ? "is-mine" : ""} ${leader && votes === leader ? "is-leading" : ""}`}>
                  {item.image_url && <img src={item.image_url} alt="" />}
                  <div className="board-option-body">
                    <h2>{item.name}</h2>
                    <p>
                      {item.price !== null && <strong>{formatAmount(item.price)}</strong>}
                      {item.store && <span> · {item.store}</span>}
                    </p>
                    <span className="board-bar" aria-hidden="true">
                      <span style={{ width: `${share}%` }} />
                    </span>
                    <small>
                      {votes} vote{votes === 1 ? "" : "s"}
                      {board.total_votes ? ` · ${share}%` : ""}
                    </small>
                    <div className="board-actions">
                      <button
                        type="button"
                        className={`button ${mine ? "button-secondary" : "button-primary"} button-sm`}
                        onClick={() => vote(index)}
                        disabled={busy || mine}
                      >
                        <Icon name={mine ? "check" : "heart"} size={14} />
                        {mine ? "Your vote" : "Vote for this"}
                      </button>
                      {item.url && (
                        <a className="button button-ghost button-sm" href={item.url} target="_blank" rel="noopener noreferrer">
                          <Icon name="external" size={14} />
                          See listing
                        </a>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          {error && (
            <div className="alert alert-error" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          )}
        </>
      )}
    </main>
  );
}
