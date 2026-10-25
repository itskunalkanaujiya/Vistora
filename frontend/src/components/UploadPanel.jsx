import { useRef, useState } from "react";
import Emoji3D from "./Emoji3D.jsx";
import Icon from "./Icon.jsx";
import { TOOLS } from "../lib/tools.js";

const LIST_EXAMPLE = [
  "Diwali list:",
  "kurta for papa",
  "saree for mummy, 3000 tak",
  "2 diya sets",
  "dry fruit gift box",
].join("\n");

// One step per search stage reported by the backend. Within a stage the
// bar eases from `from` towards `to` (it never stalls, never overshoots);
// `seconds` is the stage's typical length, which sets the easing speed.
const SEARCH_STEPS = [
  { label: "Uploading your photo", from: 0, to: 9, seconds: 1 },
  { label: "Identifying the product", from: 10, to: 44, seconds: 5 },
  { label: "Finding matching listings", from: 45, to: 74, seconds: 2 },
  { label: "Comparing prices and stock", from: 75, to: 97, seconds: 2.5 },
];

function stageProgress(stage, stageElapsed) {
  const step = SEARCH_STEPS[stage];
  return step.from + (step.to - step.from) * (1 - Math.exp(-stageElapsed / step.seconds));
}

function SearchProgress({ stage, stageElapsed, isComplete, identifiedQuery }) {
  const progress = isComplete ? 100 : stageProgress(stage, stageElapsed);
  const current = stage;

  return (
    <div className="search-progress">
      <div className="progress-head">
        <span>{isComplete ? "Results ready" : SEARCH_STEPS[current].label}</span>
        <span className="progress-percent">{Math.floor(progress)}%</span>
      </div>

      <div
        className="progress-track"
        role="progressbar"
        aria-label="Search progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.floor(progress)}
      >
        <span className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      {identifiedQuery && (
        <p className="progress-identified">
          <Icon name="scan" size={14} />
          Identified as <strong>{identifiedQuery}</strong>
        </p>
      )}

      <ol className="progress-steps">
        {SEARCH_STEPS.map((step, index) => {
          const state =
            isComplete || index < current
              ? "done"
              : index === current
                ? "active"
                : "pending";

          return (
            <li key={step.label} className={`progress-step is-${state}`}>
              <span className="progress-dot">
                {state === "done" ? (
                  <Icon name="check" size={12} />
                ) : state === "active" ? (
                  <span className="spinner" />
                ) : null}
              </span>
              <span>{step.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// What a photo can be used for; the chosen one sets the button and the hints.
const PURPOSES = [
  {
    key: "product",
    tool: "photo",
    cardTitle: "Find a product",
    cardLine: "Every store, cheapest first",
    icon: "search",
    label: "Find this product",
    hint: "Every store selling it, cheapest first",
    action: "Find matching products",
    busy: "Searching",
    drop: "a product photo or screenshot",
    short: "Product",
    gets: ["Every store selling it", "Cheapest price first", "Cheaper lookalikes"],
    tips: ["One product in the frame", "Plain background", "Good light, in focus"],
  },
  {
    key: "outfit",
    tool: "outfit",
    cardTitle: "Find the outfit",
    cardLine: "Shop what they're wearing",
    icon: "shirt",
    label: "Find the outfit",
    hint: "Shop each item the person is wearing",
    action: "Find the outfit",
    busy: "Finding the outfit…",
    drop: "a photo of someone's outfit",
    short: "Outfit",
    gets: ["Every item they wear", "Shoppable options each", "Price of the whole look"],
    tips: ["Full-length photo", "One person in the frame", "Clear and well lit"],
  },
  {
    key: "rate",
    tool: "rate",
    cardTitle: "Rate my outfit",
    cardLine: "A score, with reasons",
    icon: "star",
    label: "Rate my outfit",
    hint: "A style score and tips to improve it",
    action: "Rate my outfit",
    busy: "Rating your outfit…",
    drop: "a photo of your outfit, ideally full length",
    short: "Rate outfit",
    gets: ["A score out of 10", "The reason behind each score", "Items that improve the look"],
    tips: ["Full length works best", "Good light, no filter", "One person in the frame"],
  },
  {
    key: "room",
    tool: "room",
    cardTitle: "Shop a room",
    cardLine: "Furniture and decor",
    icon: "box",
    label: "Shop this room",
    hint: "Furniture, lighting and decor in the photo",
    action: "Shop this room",
    busy: "Shopping the room…",
    drop: "a photo of a room",
    short: "Room",
    gets: ["Furniture, lighting and decor", "Shoppable options each", "Price of the whole room"],
    tips: ["A wide shot of the room", "Daylight if you can", "Tidy the corners you want"],
  },
  {
    key: "list",
    tool: "list",
    cardTitle: "Shop my list",
    cardLine: "Handwritten or typed",
    icon: "bag",
    label: "Shop my list",
    hint: "A handwritten list or chat screenshot",
    action: "Shop my list",
    busy: "Reading your list…",
    drop: "a photo of your shopping list",
    short: "List",
    gets: ["Every line searched", "The best price picked", "A total for your cart"],
    tips: ["Clear handwriting or a screenshot", "Quantities and budgets are read", "Hindi and Hinglish work"],
  },
];

function formatFileSize(bytes) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function UploadPanel({
  file,
  previewUrl,
  isSearching,
  isComplete,
  elapsed,
  stage,
  stageElapsed,
  identifiedQuery,
  error,
  onSelect,
  onRemove,
  isCropped,
  onCrop,
  onUndoCrop,
  purpose = "product",
  onPurposeChange,
  onRun,
  isBusy = false,
  onTypedList,
  onOpenTool,
}) {
  const inputRef = useRef(null);
  const cameraRef = useRef(null);
  const dragDepth = useRef(0);
  const [isDragging, setIsDragging] = useState(false);
  const [typing, setTyping] = useState(false);
  const [listText, setListText] = useState("");
  const chosen = PURPOSES.find((option) => option.key === purpose) || PURPOSES[0];
  // A product search shows its own progress beside the photo.
  const searching = isSearching && purpose === "product";
  const working = isSearching || isBusy;
  const typedList = purpose === "list" && typing;

  const openPicker = () => inputRef.current?.click();

  const dragHandlers = {
    onDragEnter: (event) => {
      event.preventDefault();
      dragDepth.current += 1;
      setIsDragging(true);
    },
    onDragOver: (event) => event.preventDefault(),
    onDragLeave: (event) => {
      event.preventDefault();
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setIsDragging(false);
    },
    onDrop: (event) => {
      event.preventDefault();
      dragDepth.current = 0;
      setIsDragging(false);
      if (!working) onSelect(event.dataTransfer.files?.[0]);
    },
  };

  return (
    <div className="panel search-panel photo-tool">
      <fieldset className="purpose-picker" disabled={working}>
        <legend>What should we do with the photo?</legend>
        <div className="purpose-cards" role="presentation">
          {PURPOSES.map((option) => (
            <label key={option.key} className={`purpose-card ${purpose === option.key ? "is-active" : ""}`}>
              <input
                type="radio"
                name="photo-purpose"
                value={option.key}
                checked={purpose === option.key}
                onChange={() => onPurposeChange(option.key)}
              />
              <span className="purpose-art">
                <Emoji3D name={TOOLS[option.tool].art} size={40} />
              </span>
              <strong>{option.cardTitle}</strong>
              <small>{option.cardLine}</small>
              <span className="purpose-tick" aria-hidden="true">
                <Icon name="check" size={12} />
              </span>
            </label>
          ))}
          {onOpenTool && (
            <button type="button" className="purpose-card purpose-link" onClick={() => onOpenTool("gift")}>
              <span className="purpose-art">
                <Emoji3D name={TOOLS.gift.art} size={40} />
              </span>
              <strong>Find a gift</strong>
              <small>Ideas for anyone, any budget</small>
              <span className="purpose-tick purpose-go" aria-hidden="true">
                <Icon name="arrowRight" size={12} />
              </span>
            </button>
          )}
        </div>
      </fieldset>

      {typedList ? (
        <form
          className="typed-list"
          onSubmit={(event) => {
            event.preventDefault();
            if (listText.trim().length >= 3 && !working) onTypedList(listText.trim());
          }}
        >
          <textarea
            className="plan-input list-input"
            value={listText}
            onChange={(event) => setListText(event.target.value)}
            rows={6}
            maxLength={2000}
            placeholder={LIST_EXAMPLE}
            aria-label="Your shopping list"
          />
          {error && (
            <div className="alert alert-error" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          )}
          <button type="submit" className="button button-primary button-lg search-button" disabled={listText.trim().length < 3 || working}>
            {isBusy ? (
              <>
                <span className="spinner spinner-light" />
                {chosen.busy}
              </>
            ) : (
              <>
                <Icon name="bag" size={18} />
                Shop my list
              </>
            )}
          </button>
          <button type="button" className="link-button" onClick={() => setTyping(false)}>
            <Icon name="camera" size={14} />
            Use a photo of the list instead
          </button>
        </form>
      ) : (
        <>
          {previewUrl ? (
            <div className={`preview ${working ? "is-scanning" : ""}`} {...dragHandlers}>
              <div className="preview-frame">
                <img src={previewUrl} alt="Your photo" />
                {working && <span className="scan-line" aria-hidden="true" />}
              </div>

              <div className="preview-side">
                {searching ? (
                  <SearchProgress
                    stage={stage}
                    stageElapsed={stageElapsed}
                    isComplete={isComplete}
                    identifiedQuery={identifiedQuery}
                  />
                ) : (
                  <>
                    <div className="file-chip">
                      <Icon name="image" size={16} />
                      <span className="file-name" title={file?.name}>
                        {file?.name || "Your photo"}
                      </span>
                      {isCropped && <span className="pill pill-soft pill-xs">Cropped</span>}
                      {file && <span className="file-size">{formatFileSize(file.size)}</span>}
                    </div>

                    {purpose === "product" && (
                      <p className="preview-hint">
                        {isCropped
                          ? "Only the cropped area will be searched."
                          : "Other things in the photo? Crop to just the product for better matches."}
                      </p>
                    )}

                    <div className="preview-actions">
                      {purpose === "product" && (
                        <button type="button" className="button button-secondary button-sm" onClick={onCrop} disabled={working}>
                          <Icon name="crop" size={15} />
                          {isCropped ? "Adjust crop" : "Crop"}
                        </button>
                      )}
                      {isCropped && (
                        <button type="button" className="button button-ghost button-sm" onClick={onUndoCrop} disabled={working}>
                          <Icon name="undo" size={15} />
                          Undo crop
                        </button>
                      )}
                      <button type="button" className="button button-secondary button-sm" onClick={openPicker} disabled={working}>
                        <Icon name="refresh" size={15} />
                        Replace
                      </button>
                      <button type="button" className="button button-ghost button-sm" onClick={onRemove} disabled={working}>
                        <Icon name="x" size={15} />
                        Remove
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div
              className={`dropzone ${isDragging ? "is-dragging" : ""}`}
              role="button"
              tabIndex={0}
              onClick={openPicker}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  openPicker();
                }
              }}
              {...dragHandlers}
            >
              <span className="dropzone-icon">
                <Icon name="upload" size={22} />
              </span>
              <p className="dropzone-title">
                <span className="only-pointer">
                  <strong>Upload {chosen.drop}</strong>
                </span>
                <span className="only-touch">
                  <strong>Tap to choose {chosen.drop}</strong>
                </span>
              </p>
              <p className="dropzone-subtitle">Click to browse, drag and drop, or paste with Ctrl+V</p>
              <ul className="dropzone-formats" aria-label="Accepted files">
                <li>JPG</li>
                <li>PNG</li>
                <li>WebP</li>
                <li>up to 8 MB</li>
              </ul>
            </div>
          )}

          {!previewUrl && (
            <p className="photo-tips-line">
              <Icon name="sparkles" size={13} />
              <span>
                <strong>Tips:</strong> {chosen.tips.join(" · ")}
              </span>
            </p>
          )}

          {!previewUrl && (
            <button
              type="button"
              className="button button-secondary camera-button only-touch"
              onClick={() => cameraRef.current?.click()}
            >
              <Icon name="camera" size={18} />
              Take a photo
            </button>
          )}

          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={(event) => {
              onSelect(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => {
              onSelect(event.target.files?.[0]);
              event.target.value = "";
            }}
          />

          {error && (
            <div className="alert alert-error" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          )}

          <button
            type="button"
            className={`button button-primary button-lg search-button ${working ? "is-loading" : ""}`}
            onClick={() => onRun(purpose)}
            disabled={!file || working}
          >
            {searching ? (
              <>
                {isComplete ? <Icon name="check" size={18} /> : <span className="spinner spinner-light" />}
                {isComplete ? "Done" : `Searching… ${Math.floor(elapsed)}s`}
              </>
            ) : working ? (
              <>
                <span className="spinner spinner-light" />
                {chosen.busy}
              </>
            ) : (
              <>
                <Icon name={chosen.icon} size={18} />
                {chosen.action}
              </>
            )}
          </button>

          {purpose === "list" && (
            <button type="button" className="link-button" onClick={() => setTyping(true)}>
              <Icon name="pencil" size={14} />
              No photo? Type your list instead
            </button>
          )}
        </>
      )}

      <p className="panel-footnote">
        <Icon name="shield" size={13} />
        Your photo is only used for this search and isn't kept.
      </p>
    </div>
  );
}
