import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";
import { analyseColours } from "../lib/palette.js";
import { prepareForUpload } from "../lib/resizeImage.js";
import { ALLOWED_IMAGE_TYPES, MAX_IMAGE_SIZE } from "../lib/products.js";

function Swatches({ colours, muted = false }) {
  return (
    <ul className={`swatches ${muted ? "is-muted" : ""}`}>
      {colours.map((colour) => (
        <li key={colour.name}>
          <span className="swatch" style={{ background: colour.hex }} aria-hidden="true" />
          {colour.name}
        </li>
      ))}
    </ul>
  );
}

/** Each colour with the reason it was picked; palettes saved earlier have no reasons. */
function ColourList({ colours, muted = false }) {
  if (!colours.some((colour) => colour.reason)) return <Swatches colours={colours} muted={muted} />;

  return (
    <ul className={`colour-reasons ${muted ? "is-muted" : ""}`}>
      {colours.map((colour) => (
        <li key={colour.name}>
          <span className="swatch" style={{ background: colour.hex }} aria-hidden="true" />
          <span>
            <strong>{colour.name}</strong>
            {colour.reason && <small>{colour.reason}</small>}
          </span>
        </li>
      ))}
    </ul>
  );
}

const CONFIDENCE_NOTE = {
  low: "Low confidence",
  medium: "Medium confidence",
};

/** What the model saw in the selfie, and how sure it is of each reading. */
function Observations({ observations }) {
  return (
    <ul className="colours-observed">
      {observations.map((item) => (
        <li key={item.area}>
          <div>
            <strong>{item.label}</strong>
            <span>{item.finding}</span>
            {item.confidence !== "high" && (
              <em title="The photo shows this only partly">
                {item.confidence === "low" ? "Hard to see" : "Partly clear"}
              </em>
            )}
          </div>
          {item.evidence && item.confidence !== "low" && <small>{item.evidence}</small>}
        </li>
      ))}
    </ul>
  );
}

/**
 * "Colours that suit you": take or upload a selfie, see the palette, and
 * save it so results show "Suits you" on matching colours.
 */
export default function ColoursDialog({ palette, onSave, onClose }) {
  const [result, setResult] = useState(palette);
  const [previewUrl, setPreviewUrl] = useState("");
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const dialogRef = useRef(null);

  useEffect(() => {
    dialogRef.current?.focus();
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => () => previewUrl && URL.revokeObjectURL(previewUrl), [previewUrl]);

  async function check(file) {
    if (!file) return;
    if (!ALLOWED_IMAGE_TYPES.includes(file.type) || file.size > MAX_IMAGE_SIZE) {
      setError("Please choose a JPG, PNG or WebP photo under 8 MB.");
      return;
    }
    setError("");
    setPreviewUrl(URL.createObjectURL(file));
    setIsChecking(true);
    try {
      setResult(await analyseColours(await prepareForUpload(file)));
    } catch (checkError) {
      setError(
        checkError instanceof TypeError
          ? "Can't reach the Vistora server. Check that the backend is running."
          : checkError.message
      );
    } finally {
      setIsChecking(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <section
        ref={dialogRef}
        className="modal colours-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="colours-title"
        tabIndex={-1}
      >
        <header className="modal-header">
          <div>
            <span className="eyebrow">New · Personal</span>
            <h2 id="colours-title">Colours that suit you</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="colours-body">
          <div className="colours-photo">
            {previewUrl ? (
              <img src={previewUrl} alt="Your selfie" />
            ) : (
              <span className="colours-photo-empty" aria-hidden="true">
                <Icon name="palette" size={30} />
              </span>
            )}
            {isChecking && (
              <span className="colours-scanning">
                <span className="spinner" />
                Reading your colouring…
              </span>
            )}
          </div>

          <div className="colours-result">
            {result ? (
              <>
                <p className="colours-season">
                  <strong>{result.season || "Your palette"}</strong>
                  {result.undertone && <span className="pill pill-outline">{result.undertone} undertone</span>}
                </p>
                <ul className="palette-strip" aria-label="Your best colours at a glance">
                  {result.best.map((colour) => (
                    <li key={colour.name} style={{ background: colour.hex }} title={colour.name} />
                  ))}
                </ul>
                {CONFIDENCE_NOTE[result.confidence] && (
                  <p className="colours-caution" role="note">
                    <Icon name="alert" size={15} />
                    <span>
                      <strong>{CONFIDENCE_NOTE[result.confidence]}.</strong>{" "}
                      {result.photo_issues?.length > 0
                        ? `The photo has ${result.photo_issues.join(", ")}, which can change how your colours read.`
                        : "Some of your features were hard to read in this photo."}{" "}
                      For a sharper result, try a selfie facing a window in daylight, with no filter.
                    </span>
                  </p>
                )}
                {result.summary && (
                  <>
                    <h3>Why this palette</h3>
                    <p className="colours-summary">{result.summary}</p>
                  </>
                )}
                {result.observations?.length > 0 && (
                  <>
                    <h3>What we saw</h3>
                    <Observations observations={result.observations} />
                  </>
                )}
                <h3>Your best colours</h3>
                <ColourList colours={result.best} />
                {result.avoid?.length > 0 && (
                  <>
                    <h3>Less flattering</h3>
                    <ColourList colours={result.avoid} muted />
                  </>
                )}
              </>
            ) : (
              <>
                <p className="colours-intro">
                  Take a selfie or upload a clear, front-facing photo in daylight, without filters
                  or makeup if you can. AI reads your undertone and contrast and picks the colours
                  that flatter you.
                </p>
                <p className="colours-intro">
                  Then results show <span className="suits-chip">Suits you</span> on listings in
                  your colours, and you can show only those.
                </p>
              </>
            )}
            {error && (
              <p className="alert alert-error" role="alert">
                <Icon name="alert" size={15} />
                {error}
              </p>
            )}
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="user"
          hidden
          onChange={(event) => {
            check(event.target.files?.[0]);
            event.target.value = "";
          }}
        />

        <footer className="modal-footer">
          <p className="panel-footnote">
            <Icon name="shield" size={13} />
            Your selfie is only used for this check and isn't kept. The palette stays in this browser.
          </p>
          <div className="modal-actions">
            {palette && (
              <button type="button" className="button button-ghost button-sm" onClick={() => onSave(null)}>
                <Icon name="trash" size={14} />
                Forget my colours
              </button>
            )}
            <button
              type="button"
              className="button button-secondary"
              onClick={() => inputRef.current?.click()}
              disabled={isChecking}
            >
              <Icon name="camera" size={16} />
              {result ? "Try another selfie" : "Take or upload a selfie"}
            </button>
            {result && result !== palette && (
              <button type="button" className="button button-primary" onClick={() => onSave(result)}>
                <Icon name="check" size={16} />
                Use these colours
              </button>
            )}
          </div>
        </footer>
      </section>
    </div>
  );
}
