import { useEffect, useMemo, useState } from "react";
import Icon from "./Icon.jsx";
import ProductCard, { ProductCardSkeleton } from "./ProductCard.jsx";
import { formatAmount, getNumericPrice, getProductId } from "../lib/products.js";
import { computeDeals } from "../lib/deals.js";

const THUMBNAIL_SIZE = 160;
const BOX_PADDING = 0.15; // share of the box added on each side

/** Crop each item's box from the photo into a small square thumbnail. */
function useItemThumbnails(photoUrl, items) {
  const [thumbnails, setThumbnails] = useState({});
  const boxes = items.map((item) => `${item.id}:${item.box || ""}`).join("|");

  useEffect(() => {
    if (!photoUrl || !boxes) return undefined;
    let active = true;
    const image = new Image();
    image.onload = () => {
      const crops = {};
      for (const item of items) {
        if (!item.box) continue;
        const [x1, y1, x2, y2] = item.box;
        const padX = (x2 - x1) * BOX_PADDING;
        const padY = (y2 - y1) * BOX_PADDING;
        const left = Math.max(0, x1 - padX) * image.naturalWidth;
        const top = Math.max(0, y1 - padY) * image.naturalHeight;
        const width = Math.min(1, x2 + padX) * image.naturalWidth - left;
        const height = Math.min(1, y2 + padY) * image.naturalHeight - top;
        // Square crop around the box centre, so thumbnails line up.
        const side = Math.max(width, height);
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = THUMBNAIL_SIZE;
        const context = canvas.getContext("2d");
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, THUMBNAIL_SIZE, THUMBNAIL_SIZE);
        context.drawImage(
          image,
          left + width / 2 - side / 2,
          top + height / 2 - side / 2,
          side,
          side,
          0,
          0,
          THUMBNAIL_SIZE,
          THUMBNAIL_SIZE
        );
        crops[item.id] = canvas.toDataURL("image/jpeg", 0.85);
      }
      if (active) setThumbnails(crops);
    };
    image.src = photoUrl;
    return () => {
      active = false;
    };
    // `boxes` captures the items' identities and boxes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoUrl, boxes]);

  return thumbnails;
}

function capitalise(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

/** Every option for an item, without repeats. */
function itemProducts(item) {
  const unique = new Map();
  [...(item.best_matches || []), ...(item.cheapest_alternatives || [])].forEach((product) =>
    unique.set(getProductId(product), product)
  );
  return [...unique.values()];
}

/** A listing's key, as the Budget look planner's picks name it. */
function listingKey(product) {
  return product.product_url || product.name;
}

/** The listing picked for a planned piece, or undefined. */
function pickedProduct(item, picks) {
  const key = picks?.[item.id];
  return key ? itemProducts(item).find((product) => listingKey(product) === key) : undefined;
}

/** Lowest known price among an item's options, or null. */
function lowestPrice(item) {
  const prices = itemProducts(item)
    .map(getNumericPrice)
    .filter((price) => price !== null);
  return prices.length ? Math.min(...prices) : null;
}

function scrollToItem(id) {
  document.getElementById(`outfit-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function ItemThumb({ src, className = "" }) {
  return src ? (
    <img className={`outfit-thumb ${className}`} src={src} alt="" />
  ) : (
    <span className={`outfit-thumb outfit-thumb-empty ${className}`} aria-hidden="true">
      <Icon name="shirt" size={18} />
    </span>
  );
}

/** The photo with a numbered marker on each item and the active item outlined. */
function OutfitPhoto({ photoUrl, alt, items, activeId, onActivate, scanning }) {
  const active = items.find((item) => item.id === activeId && item.box);

  return (
    <div className={`outfit-photo-frame ${scanning ? "is-scanning" : ""}`}>
      <img src={photoUrl} alt={alt} />
      {scanning && <span className="scan-line" aria-hidden="true" />}
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
      {items.map((item, index) =>
        item.box ? (
          <button
            key={item.id}
            type="button"
            className={`outfit-marker ${item.id === activeId ? "is-active" : ""}`}
            style={{
              left: `${((item.box[0] + item.box[2]) / 2) * 100}%`,
              top: `${((item.box[1] + item.box[3]) / 2) * 100}%`,
            }}
            onMouseEnter={() => onActivate(item.id)}
            onFocus={() => onActivate(item.id)}
            onClick={() => scrollToItem(item.id)}
            aria-label={`${capitalise(item.type)}: see options`}
          >
            {index + 1}
          </button>
        ) : null
      )}
    </div>
  );
}

const SCORE_RING_RADIUS = 34;
const SCORE_AREAS = [
  ["colours", "Colours", "palette", "How well the colours and patterns work together"],
  ["fit", "Fit", "layers", "How the garments sit and balance"],
  ["styling", "Styling", "sparkles", "Footwear, accessories and finishing"],
  ["occasion", "Occasion", "clock", "Whether every piece suits the same setting"],
];

/** How good a score is, in words, and the colour family that goes with it. */
function scoreTone(score) {
  if (score >= 8.5) return { key: "great", label: "Excellent look" };
  if (score >= 7.5) return { key: "great", label: "Strong look" };
  if (score >= 6.5) return { key: "good", label: "Good look" };
  if (score >= 5) return { key: "fair", label: "Needs a few changes" };
  return { key: "low", label: "Needs a rethink" };
}

/** Rate my outfit: the score, why, and the evidence behind each area. */
function RatingSummary({ rating }) {
  const circumference = 2 * Math.PI * SCORE_RING_RADIUS;
  const share = Math.min(1, Math.max(0, rating.score / 10));
  const tone = scoreTone(rating.score);
  const hasDetails = rating.details && Object.keys(rating.details).length > 0;
  const areas = SCORE_AREAS.filter(([key]) => rating.scores?.[key] != null);

  return (
    <div className={`rating-card rating-${tone.key}`}>
      <div className="rating-hero">
        <div className="rating-score" role="img" aria-label={`Style score ${rating.score} out of 10`}>
          <svg viewBox="0 0 80 80" aria-hidden="true">
            <circle className="rating-track" cx="40" cy="40" r={SCORE_RING_RADIUS} />
            <circle
              className="rating-fill"
              cx="40"
              cy="40"
              r={SCORE_RING_RADIUS}
              strokeDasharray={circumference}
              strokeDashoffset={circumference * (1 - share)}
            />
          </svg>
          <span>
            <strong>{rating.score.toFixed(1)}</strong>
            <small>out of 10</small>
          </span>
        </div>
        <div className="rating-text">
          <span className="rating-tone">{tone.label}</span>
          <p className="rating-verdict">{rating.verdict}</p>
          {rating.occasion && rating.occasion.toLowerCase() !== "unclear" && (
            <span className="pill pill-outline">
              <Icon name="sparkles" size={12} />
              Best for: {rating.occasion}
            </span>
          )}
        </div>
      </div>

      {areas.length > 0 && (
        <ul className="rating-tiles" aria-label="Scores by area">
          {areas.map(([key, label, icon]) => {
            const score = rating.scores[key];
            const level = scoreTone(score).key;
            return (
              <li key={key} className={`tile-${level}`}>
                <span className="rating-tile-label">
                  <Icon name={icon} size={14} />
                  {label}
                </span>
                <strong>{score.toFixed(1)}</strong>
                <span className="rating-bar" aria-hidden="true">
                  <span style={{ width: `${score * 10}%` }} />
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {rating.summary && (
        <section className="rating-why">
          <h3>
            <Icon name="sparkles" size={15} />
            Why this rating
          </h3>
          <p>{rating.summary}</p>
        </section>
      )}

      {rating.wearing?.length > 0 && (
        <section className="rating-seen">
          <h3>What your stylist saw</h3>
          <ul>
            {rating.wearing.map((piece) => (
              <li key={piece}>{capitalise(piece)}</li>
            ))}
          </ul>
        </section>
      )}

      {rating.strengths?.length > 0 && (
        <section className="rating-works">
          <h3>What works</h3>
          <ul className="rating-strengths">
            {rating.strengths.map((strength) => (
              <li key={strength}>
                <Icon name="check" size={14} />
                {capitalise(strength)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {hasDetails && (
        <section className="rating-breakdown">
          <h3>How each score is worked out</h3>
          <ul>
            {SCORE_AREAS.filter(([key]) => rating.details[key]).map(([key, label, icon, aim]) => {
              const detail = rating.details[key];
              const level = scoreTone(detail.score).key;
              return (
                <li key={key} className={`detail-${level}`}>
                  <header>
                    <span className="detail-icon">
                      <Icon name={icon} size={16} />
                    </span>
                    <div>
                      <strong>{label}</strong>
                      <small>{aim}</small>
                    </div>
                    {detail.confidence === "medium" && (
                      <span className="detail-chip" title="Part of this area is out of view, so it counts a little less in the score">
                        Partly visible
                      </span>
                    )}
                    <b className="detail-score">{detail.score.toFixed(1)}</b>
                  </header>
                  {detail.confidence === "low" && (
                    <p className="detail-limit">
                      <Icon name="alert" size={13} />
                      Mostly out of view, so this counts for much less in the score.
                    </p>
                  )}
                  {detail.evidence && (
                    <div className="detail-block">
                      <span>What we saw</span>
                      <p>{detail.evidence}</p>
                    </div>
                  )}
                  {detail.reason && (
                    <div className="detail-block">
                      <span>Why it scores this</span>
                      <p>{detail.reason}</p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="rating-method">
            The overall score is the average of these four areas. An area the photo shows only in part counts for
            less, so a cropped photo doesn't lose points for what it can't show.
          </p>
          {rating.not_visible?.length > 0 && (
            <p className="rating-hidden">
              <Icon name="alert" size={14} />
              Not visible in the photo, so not scored or advised on: {rating.not_visible.join(", ")}.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

/** The Budget look planner's headline: the look and its total against the budget. */
function PlanSummary({ outfit, total, remaining }) {
  const budget = outfit.budget || 0;
  const over = total > budget;
  const share = budget ? Math.min(100, (total / budget) * 100) : 0;

  if (!budget) {
    // A shopping list: the cart total, counting quantities.
    const count = outfit.items.reduce((sum, item) => sum + (item.quantity || 1), 0);
    return (
      <div className="plan-summary">
        <h2>{outfit.title || "Your shopping list"}</h2>
        {remaining === 0 && (
          <p className="plan-total">
            <strong>{formatAmount(total)}</strong>
            <span>
              for {count} thing{count === 1 ? "" : "s"} on your list, best pick for each
            </span>
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={`plan-summary ${over ? "is-over" : ""}`}>
      <h2>{outfit.title || "Your look"}</h2>
      {remaining === 0 && (
        <>
          <p className="plan-total">
            <strong>{formatAmount(total)}</strong>
            <span>of your {formatAmount(budget)} budget</span>
          </p>
          <span className="plan-meter" aria-hidden="true">
            <span style={{ width: `${share}%` }} />
          </span>
          <p className="plan-note">
            {over
              ? `${formatAmount(total - budget)} over budget: even the cheapest options add up to more. Swap a piece or raise the budget.`
              : `${formatAmount(budget - total)} left in your budget.`}
          </p>
        </>
      )}
    </div>
  );
}

function ItemSection({ item, index, thumbnail, savedIds, onToggleSave, onTryOn, onMore, onExactMatch, pickKey, onPick }) {
  const products = itemProducts(item);
  const lowest = lowestPrice(item);
  const deals = computeDeals(products);

  return (
    <section className="outfit-section" id={`outfit-${item.id}`}>
      <header className="outfit-section-header">
        <span className="outfit-number" aria-hidden="true">
          {index + 1}
        </span>
        <ItemThumb src={thumbnail} />
        <div className="outfit-section-title">
          <h3>{capitalise(item.type)}</h3>
          <p>{capitalise(item.description)}</p>
          {item.reason && <p className="outfit-reason">{capitalise(item.reason)}</p>}
        </div>
        {!item.pending && lowest !== null && (
          <span className="outfit-from">
            <small>from</small>
            {formatAmount(lowest)}
          </span>
        )}
        {!item.pending && onExactMatch && item.box && (
          <button
            type="button"
            className="button button-ghost button-sm outfit-exact"
            onClick={() => onExactMatch(item)}
            title="Search this item's part of your photo with Google Lens (uses one photo search)"
          >
            <Icon name="scan" size={14} />
            Exact match
          </button>
        )}
        {!item.pending && products.length > 0 && (
          <button type="button" className="button button-ghost button-sm outfit-more" onClick={() => onMore(item.query)}>
            More like this
            <Icon name="arrowRight" size={14} />
          </button>
        )}
      </header>

      {item.pending ? (
        <div className="outfit-scroller" aria-busy="true" aria-label="Finding options">
          {Array.from({ length: 4 }, (_, skeleton) => (
            <ProductCardSkeleton key={skeleton} />
          ))}
        </div>
      ) : products.length ? (
        <div className="outfit-scroller">
          {products.map((product, position) => (
            <ProductCard
              key={getProductId(product) || position}
              product={product}
              isSaved={savedIds.has(getProductId(product))}
              onToggleSave={onToggleSave}
              onTryOn={onTryOn}
              highlight={getNumericPrice(product) === lowest && lowest !== null ? "Lowest" : null}
              deal={deals.get(getProductId(product))}
              pick={
                onPick
                  ? { picked: listingKey(product) === pickKey, onPick: () => onPick(item.id, listingKey(product)) }
                  : undefined
              }
            />
          ))}
        </div>
      ) : (
        <p className="outfit-empty">
          <Icon name="alert" size={15} />
          {item.failed
            ? "Couldn't search for this item right now. Try again in a moment."
            : "No matching listings found for this item."}
          <button type="button" className="button button-ghost button-sm" onClick={() => onMore(item.query)}>
            Search “{item.query}”
          </button>
        </p>
      )}
    </section>
  );
}

/**
 * Results of "Find the outfit": the photo with a marker on every item, a
 * summary with the price of the whole look, then a swipeable row of
 * shopping options per item.
 *
 * Also shows, by outfit.kind: "look" (Complete the look: the product being
 * styled and what goes with it), "rating" (Rate my outfit), "room" (Shop
 * this room: the pieces in a room photo) and "plan" (Budget look planner:
 * the planned pieces, one picked listing each, and the total against the
 * budget; onPick swaps a piece's listing).
 */
export default function OutfitView({ outfit, photoUrl, savedIds, onToggleSave, onTryOn, onMore, onBack, onExactMatch, onPick }) {
  const items = useMemo(() => outfit.items || [], [outfit.items]);
  const isLook = outfit.kind === "look";
  const isRating = outfit.kind === "rating";
  const isRoom = outfit.kind === "room";
  const isPlan = outfit.kind === "plan";
  const isGift = outfit.kind === "gift";
  const isList = outfit.kind === "list";
  // Plans and lists pick one listing per item and add up a total.
  const picking = isPlan || isList;
  const baseProduct = isLook ? outfit.product : null;
  // Suggestions (a look's, a rating's or a plan's) aren't in a photo, so
  // there's nothing to crop; use each item's picked or first listing.
  const suggested = isLook || isRating || isPlan || isGift || isList;
  const cropped = useItemThumbnails(suggested ? "" : photoUrl, items);
  const thumbnails = suggested
    ? Object.fromEntries(
        items.map((item) => [item.id, (pickedProduct(item, outfit.picks) || itemProducts(item)[0])?.image_url])
      )
    : cropped;
  const planTotal = picking
    ? items.reduce(
        (sum, item) => sum + (getNumericPrice(pickedProduct(item, outfit.picks) || {}) ?? 0) * (item.quantity || 1),
        0
      )
    : 0;
  const noun = isRoom ? "piece" : isGift ? "idea" : "item";
  const [activeId, setActiveId] = useState(null);
  const basePrice = baseProduct ? getNumericPrice(baseProduct) : null;

  const scanning = isRating ? !outfit.rating : items.length === 0;
  const remaining = items.filter((item) => item.pending).length;
  const lookPrices = items.map(lowestPrice).filter((price) => price !== null);
  const lookTotal = lookPrices.reduce((sum, price) => sum + price, basePrice ?? 0);
  const pricedCount = lookPrices.length + (basePrice !== null ? 1 : 0);
  const audience = outfit.gender && outfit.gender !== "unisex" ? outfit.gender : "";

  return (
    <section className="results container outfit" onMouseLeave={() => setActiveId(null)}>
      {onBack && (
        <button type="button" className="button button-ghost button-sm outfit-back" onClick={onBack}>
          <Icon name="undo" size={15} />
          Back to results
        </button>
      )}
      <div className={`outfit-summary ${photoUrl ? "" : "no-photo"}`}>
        {photoUrl && (
          <OutfitPhoto
            photoUrl={photoUrl}
            alt={isLook ? baseProduct?.name || "The product" : isRoom ? "Your room photo" : "Your outfit photo"}
            items={items}
            activeId={activeId}
            onActivate={setActiveId}
            scanning={scanning}
          />
        )}

        <div className="outfit-overview">
          <span className="eyebrow">
            {isRating
              ? "Rate my outfit"
              : isLook
                ? "Complete the look"
                : isRoom
                  ? "Shop this room"
                  : isPlan
                    ? "Budget look planner"
                    : isGift
                      ? "Gift finder"
                      : isList
                        ? "Your shopping list"
                        : "Find the outfit"}
          </span>
          {baseProduct && (
            <p className="look-base">
              Styling <strong>{baseProduct.name}</strong>
              {basePrice !== null && ` · ${formatAmount(basePrice)}`}
            </p>
          )}
          {scanning ? (
            <>
              <h2>
                {isRating
                  ? "Your stylist is looking…"
                  : isLook
                    ? "Styling the look…"
                    : isRoom
                      ? "Looking around the room…"
                      : isPlan
                        ? "Planning your look…"
                        : isGift
                          ? "Thinking of gifts…"
                          : isList
                            ? "Reading your list…"
                            : "Looking at the outfit…"}
              </h2>
              <p className="outfit-lead">
                {isRating
                  ? "AI is checking the fit, colours and accessories. This takes a few seconds."
                  : isLook
                    ? "AI is picking what goes with it. This usually takes a few seconds."
                    : isRoom
                      ? "AI is spotting the furniture, lighting and decor. This usually takes a few seconds."
                      : isPlan
                        ? "AI is choosing the pieces and splitting your budget between them."
                        : isGift
                          ? "AI is picking six ideas they'd love. This takes a few seconds."
                          : isList
                            ? "AI is reading each line and finding it in stores."
                            : "AI is spotting each item they're wearing. This usually takes a couple of seconds."}
              </p>
              <div className="outfit-list" aria-hidden="true">
                {Array.from({ length: 3 }, (_, index) => (
                  <span key={index} className="outfit-row outfit-row-skeleton">
                    <span className="outfit-thumb shimmer" />
                    <span className="skeleton-line shimmer" style={{ width: `${60 - index * 10}%` }} />
                  </span>
                ))}
              </div>
            </>
          ) : (
            <>
              {isRating && <RatingSummary rating={outfit.rating} />}
              {isRating ? (
                items.length > 0 && (
                  <h3 className="rating-fixes-title">
                    Level it up
                    {outfit.rating.personalised && (
                      <span className="suits-chip">
                        <Icon name="palette" size={12} /> In your colours
                      </span>
                    )}
                  </h3>
                )
              ) : picking ? (
                <PlanSummary outfit={outfit} total={planTotal} remaining={remaining} />
              ) : isGift ? (
                <h2>{outfit.title || "Gift ideas"}</h2>
              ) : (
                <h2>
                  {items.length} {noun}
                  {items.length === 1 ? "" : "s"} {isLook ? "that go with it" : "spotted"}
                </h2>
              )}
              {isRoom && outfit.style && <p className="look-base">Style: <strong>{outfit.style}</strong></p>}
              {(items.length > 0 || !isRating) && (
                <p className="outfit-lead">
                  {remaining > 0
                    ? `Finding shopping options for ${remaining} ${noun}${remaining === 1 ? "" : "s"}…`
                    : isPlan
                      ? "Tap a piece to see its options; swap any of them and the total updates."
                      : isList
                        ? "Tap an item to see its options; swap any of them and the total updates."
                        : isGift
                          ? `Six ideas${outfit.recipient ? ` for your ${outfit.recipient}` : ""}${outfit.budget ? ` up to ${formatAmount(outfit.budget)}` : ""}. Tap one to see where to buy it.`
                      : `Tap ${isRating ? "a suggestion" : `a ${noun}`} to see its options${audience ? ` for ${audience}` : ""}.`}
                </p>
              )}

              {remaining === 0 && pricedCount > 1 && !isRating && !picking && !isGift && (
                <div className="outfit-total">
                  <Icon name="tag" size={18} />
                  <span>
                    Get the whole {isRoom ? "room" : "look"} from <strong>{formatAmount(lookTotal)}</strong>
                    <small>
                      {basePrice !== null ? "This item plus the cheapest option for " : "Cheapest option for "}
                      {lookPrices.length === items.length ? "every" : `${lookPrices.length} of ${items.length}`} {noun}
                      {lookPrices.length === items.length ? "" : "s"}
                    </small>
                  </span>
                </div>
              )}

              <ol className="outfit-list">
                {items.map((item, index) => {
                  const lowest = lowestPrice(item);
                  const picked = picking ? pickedProduct(item, outfit.picks) : null;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={`outfit-row ${item.id === activeId ? "is-active" : ""}`}
                        onMouseEnter={() => setActiveId(item.id)}
                        onFocus={() => setActiveId(item.id)}
                        onClick={() => scrollToItem(item.id)}
                      >
                        <span className="outfit-number">{index + 1}</span>
                        <ItemThumb src={thumbnails[item.id]} />
                        <span className="outfit-row-text">
                          <strong>
                            {capitalise(item.type)}
                            {item.quantity > 1 && <span className="outfit-quantity">×{item.quantity}</span>}
                          </strong>
                          <small>
                            {capitalise(isRating || isGift ? item.reason || item.description : item.description)}
                          </small>
                        </span>
                        <span className="outfit-row-price">
                          {item.pending ? (
                            <span className="spinner" aria-label="Searching" />
                          ) : picked ? (
                            <>
                              <small>picked</small>
                              {formatAmount(getNumericPrice(picked))}
                            </>
                          ) : lowest !== null ? (
                            <>
                              <small>from</small>
                              {formatAmount(lowest)}
                            </>
                          ) : (
                            <small>No results</small>
                          )}
                        </span>
                        <Icon name="arrowRight" size={15} className="outfit-row-arrow" />
                      </button>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
      </div>

      {items.map((item, index) => (
        <ItemSection
          key={item.id}
          item={item}
          index={index}
          thumbnail={thumbnails[item.id]}
          savedIds={savedIds}
          onToggleSave={onToggleSave}
          onTryOn={onTryOn}
          onMore={onMore}
          onExactMatch={onExactMatch}
          pickKey={picking ? outfit.picks?.[item.id] : undefined}
          onPick={picking ? onPick : undefined}
        />
      ))}
    </section>
  );
}
