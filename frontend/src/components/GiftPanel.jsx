import { useState } from "react";
import Icon from "./Icon.jsx";

const PEOPLE = ["Mom", "Dad", "Brother", "Sister", "Friend", "Partner", "Kid", "Colleague"];
const OCCASIONS = ["Birthday", "Diwali", "Rakhi", "Anniversary", "Wedding", "Just because"];

const EXAMPLES = [
  { request: "Bhai ke liye birthday gift, gym ka shauk hai", budget: 2000 },
  { request: "Anniversary gift for my wife who loves reading and coffee", budget: 3000 },
  { request: "Diwali gift for a colleague", budget: 1000 },
];

/**
 * Gift finder: who it's for, what they like, the occasion and a budget, in
 * any words (Hindi and Hinglish too). AI suggests six ideas with listings.
 */
export default function GiftPanel({ onFind, isFinding, error }) {
  const [person, setPerson] = useState("");
  const [occasion, setOccasion] = useState("");
  const [about, setAbout] = useState("");
  const [budget, setBudget] = useState("");

  // The request the AI reads: the chips plus whatever was typed.
  const request = [
    occasion.trim() && occasion !== "Just because" ? `${occasion.trim()} gift` : "Gift",
    person.trim() && `for my ${person.trim().toLowerCase()}`,
    about.trim(),
  ]
    .filter(Boolean)
    .join(", ");
  const ready = Boolean(person.trim() || about.trim().length >= 3);

  function submit(next) {
    if (next) {
      setAbout(next.request);
      setBudget(String(next.budget));
      setPerson("");
      setOccasion("");
    }
    onFind(next || { request, budget: Number(budget) || null });
  }

  return (
    <div className="panel search-panel plan-panel">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !isFinding) submit();
        }}
      >
        <span className="plan-label">Who is it for?</span>
        <div className="gift-chips" role="group" aria-label="Who it's for">
          {PEOPLE.map((name) => (
            <button
              key={name}
              type="button"
              className={`example-chip ${person === name ? "is-active" : ""}`}
              aria-pressed={person === name}
              onClick={() => setPerson(person === name ? "" : name)}
            >
              {name}
            </button>
          ))}
          <input
            className="gift-other"
            value={PEOPLE.includes(person) ? "" : person}
            onChange={(event) => setPerson(event.target.value)}
            placeholder="Someone else? Type here"
            aria-label="Who it's for, if not listed"
            maxLength={30}
          />
        </div>

        <span className="plan-label">Occasion</span>
        <div className="gift-chips" role="group" aria-label="Occasion">
          {OCCASIONS.map((name) => (
            <button
              key={name}
              type="button"
              className={`example-chip ${occasion === name ? "is-active" : ""}`}
              aria-pressed={occasion === name}
              onClick={() => setOccasion(occasion === name ? "" : name)}
            >
              {name}
            </button>
          ))}
          <input
            className="gift-other"
            value={OCCASIONS.includes(occasion) ? "" : occasion}
            onChange={(event) => setOccasion(event.target.value)}
            placeholder="Another occasion? Type here"
            aria-label="Occasion, if not listed"
            maxLength={30}
          />
        </div>

        <div className="plan-row">
          <label>
            <span className="plan-label">What do they like?</span>
            <input
              id="gift-about"
              className="plan-input"
              value={about}
              onChange={(event) => setAbout(event.target.value)}
              placeholder={'e.g. gym, cooking, gadgets, reading, or "bhai ke liye, gym ka shauk"'}
              maxLength={150}
            />
          </label>
          <div className="plan-budget">
            <span className="plan-label">Budget</span>
            <label className="field field-price">
              <span aria-hidden="true">₹</span>
              <input
                type="number"
                min="100"
                step="100"
                inputMode="numeric"
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
                placeholder="2000"
                aria-label="Budget per gift in rupees"
              />
            </label>
          </div>
        </div>

        <button type="submit" className="button button-primary button-lg search-button" disabled={!ready || isFinding}>
          {isFinding ? (
            <>
              <span className="spinner spinner-light" />
              Finding gift ideas…
            </>
          ) : (
            <>
              <Icon name="sparkles" size={18} />
              Find gift ideas
            </>
          )}
        </button>
      </form>

      {error && (
        <div className="alert alert-error" role="alert">
          <Icon name="alert" size={17} />
          <span>{error}</span>
        </div>
      )}

      <div className="text-examples">
        <span>Try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example.request}
            type="button"
            className="example-chip"
            onClick={() => submit(example)}
            disabled={isFinding}
          >
            {example.request}, ₹{example.budget.toLocaleString("en-IN")}
          </button>
        ))}
      </div>
    </div>
  );
}
