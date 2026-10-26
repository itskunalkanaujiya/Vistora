import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { boardUrl, createBoard, whatsappLink } from "../lib/boards.js";

/**
 * "Ask my family": saves the picked products as a board and gives a link the
 * family can open to vote, with a WhatsApp button that has the message ready.
 */
export default function AskFamilyDialog({ products, onClose }) {
  const [title, setTitle] = useState("Which one should I buy?");
  const [boardId, setBoardId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  async function create() {
    setBusy(true);
    setError("");
    try {
      setBoardId(await createBoard(products, title.trim()));
    } catch (createError) {
      setError(
        createError instanceof TypeError
          ? "Can't reach the Vistora server. Please try again."
          : createError.message
      );
    } finally {
      setBusy(false);
    }
  }

  const link = boardId ? boardUrl(boardId) : "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy. Select the link and copy it yourself.");
    }
  }

  return (
    <div className="modal-backdrop" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal family-modal" role="dialog" aria-modal="true" aria-labelledby="family-title">
        <header className="modal-header">
          <div>
            <h2 id="family-title">
              <Icon name="heart" size={18} /> Ask my family
            </h2>
            <p>Share these {products.length} picks. Everyone with the link votes for their favourite.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="family-body">
          <ul className="family-picks">
            {products.map((product, index) => (
              <li key={`${product.product_url || product.name}-${index}`}>
                {product.image_url && <img src={product.image_url} alt="" />}
                <span>{product.name}</span>
              </li>
            ))}
          </ul>

          {!boardId ? (
            <>
              <label className="family-field">
                <span className="plan-label">Your question</span>
                <input
                  className="plan-input"
                  value={title}
                  maxLength={80}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <button type="button" className="button button-primary button-lg" onClick={create} disabled={busy}>
                {busy ? <span className="spinner spinner-light" /> : <Icon name="sparkles" size={17} />}
                {busy ? "Making the link…" : "Make the voting link"}
              </button>
            </>
          ) : (
            <>
              <input className="plan-input family-link" value={link} readOnly onFocus={(event) => event.target.select()} aria-label="Voting link" />
              <div className="family-actions">
                <a className="button button-primary" href={whatsappLink(link, title.trim())} target="_blank" rel="noopener noreferrer">
                  <Icon name="external" size={16} />
                  Share on WhatsApp
                </a>
                <button type="button" className="button button-secondary" onClick={copy}>
                  <Icon name={copied ? "check" : "clipboard"} size={16} />
                  {copied ? "Copied" : "Copy link"}
                </button>
                <a className="button button-ghost" href={link} target="_blank" rel="noopener noreferrer">
                  See the votes
                </a>
              </div>
              <p className="family-note">The link works for 14 days. Votes can be changed.</p>
            </>
          )}

          {error && (
            <div className="alert alert-error" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
