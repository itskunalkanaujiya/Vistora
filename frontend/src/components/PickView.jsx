import { useState } from "react";
import Icon from "./Icon.jsx";

const capitalise = (text) => (text ? text[0].toUpperCase() + text.slice(1) : "");

/**
 * "Tap any item": the photo with a numbered marker on everything that can be
 * bought. Tapping a marker (or its name below) searches just that item.
 */
export default function PickView({ photoUrl, items, onPick, onRescan, busy }) {
  const [activeId, setActiveId] = useState(null);
  const active = items.find((item) => item.id === activeId);

  return (
    <section className="results container pick-view">
      <div className="pick-head">
        <div>
          <span className="eyebrow">Tap any item</span>
          <h2>Tap the one you want</h2>
          <p className="results-meta">
            {items.length} item{items.length === 1 ? "" : "s"} found. We search only the one you pick.
          </p>
        </div>
        <button type="button" className="button button-ghost button-sm" onClick={onRescan} disabled={busy}>
          <Icon name="refresh" size={14} />
          Scan again
        </button>
      </div>

      <div className="pick-layout">
        <div className="outfit-photo-frame pick-photo">
          <img src={photoUrl} alt="Your photo, with the items you can tap" />
          {active && (
            <span
              className="outfit-box"
              aria-hidden="true"
              style={{
                left: `${active.box[0] * 100}%`,
                top: `${active.box[1] * 100}%`,
                width: `${(active.box[2] - active.box[0]) * 100}%`,
                height: `${(active.box[3] - active.box[1]) * 100}%`,
              }}
            />
          )}
          {items.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`outfit-marker ${item.id === activeId ? "is-active" : ""}`}
              style={{
                left: `${((item.box[0] + item.box[2]) / 2) * 100}%`,
                top: `${((item.box[1] + item.box[3]) / 2) * 100}%`,
              }}
              onMouseEnter={() => setActiveId(item.id)}
              onMouseLeave={() => setActiveId(null)}
              onFocus={() => setActiveId(item.id)}
              onBlur={() => setActiveId(null)}
              onClick={() => onPick(item)}
              disabled={busy}
              aria-label={`Search for the ${item.type}`}
            >
              {index + 1}
            </button>
          ))}
        </div>

        <ol className="pick-list">
          {items.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                className="pick-row"
                onMouseEnter={() => setActiveId(item.id)}
                onMouseLeave={() => setActiveId(null)}
                onFocus={() => setActiveId(item.id)}
                onBlur={() => setActiveId(null)}
                onClick={() => onPick(item)}
                disabled={busy}
              >
                <span className="outfit-number" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="pick-row-text">
                  <strong>{capitalise(item.type)}</strong>
                  <small>{capitalise(item.description)}</small>
                </span>
                <span className="pick-row-go">
                  <Icon name="search" size={14} />
                  Find it
                </span>
              </button>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
