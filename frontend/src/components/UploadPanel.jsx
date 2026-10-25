import { useRef, useState } from "react";
import Icon from "./Icon.jsx";

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
    icon: "search",
    label: "Find this product",
    hint: "Every store selling it, cheapest first",
    action: "Find matching products",
    busy: "Searching",
    drop: "a product photo or screenshot",
  },
  {
    key: "outfit",
    icon: "shirt",
    label: "Find the outfit",
    hint: "Shop each item the person is wearing",
    action: "Find the outfit",
    busy: "Finding the outfit…",
    drop: "a photo of someone's outfit",
  },
  {
    key: "rate",
    icon: "star",
    label: "Rate my outfit",
    hint: "A style score and tips to improve it",
    action: "Rate my outfit",
    busy: "Rating your outfit…",
    drop: "a photo of your outfit, ideally full length",
  },
  {
    key: "room",
    icon: "box",
    label: "Shop this room",
    hint: "Furniture, lighting and decor in the photo",
    action: "Shop this room",
    busy: "Shopping the room…",
    drop: "a photo of a room",
  },
  {
    key: "list",
    icon: "bag",
    label: "Shop my list",
    hint: "A handwritten list or chat screenshot",
    action: "Shop my list",
    busy: "Reading your list…",
    drop: "a photo of your shopping list",
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
        <legend>
          <span className="step-badge">1</span>
          What should we do with the photo?
        </legend>
        <div className="purpose-options">
          {PURPOSES.map((option) => (
            <label key={option.key} className={`purpose-option ${purpose === option.key ? "is-active" : ""}`}>
              <input
                type="radio"
                name="photo-purpose"
                value={option.key}
                checked={purpose === option.key}
                onChange={() => onPurposeChange(option.key)}
              />
              <span className="purpose-icon">
                <Icon name={option.icon} size={19} />
              </span>
              <span className="purpose-text">
                <strong>{option.label}</strong>
                <small>{option.hint}</small>
              </span>
              <span className="purpose-check" aria-hidden="true">
                <Icon name="check" size={12} />
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <h2 className="step-title">
        <span className="step-badge">2</span>
        {typedList ? "Type your list" : previewUrl ? "Your photo" : `Add ${chosen.drop}`}
      </h2>

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

          {!previewUrl && purpose === "product" && (
            <ul className="photo-tips" aria-label="Tips for better matches">
              <li>
                <Icon name="scan" size={14} />
                One product in the frame
              </li>
              <li>
                <Icon name="image" size={14} />
                Plain background
              </li>
              <li>
                <Icon name="sparkles" size={14} />
                Good light, in focus
              </li>
            </ul>
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
