import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { canTryOn } from "../lib/tryon.js";
import { canTryOnAccessory, loadOverlay } from "../lib/accessoryTryOn.js";
import { usePalette } from "../lib/palette.js";
import { useCompare } from "../lib/compare.js";
import { usePriceWatch } from "../lib/priceWatch.js";
import {
  AVAILABILITY_LABELS,
  formatAmount,
  formatPrice,
  getNumericPrice,
  getAvailability,
  getMatchLevel,
} from "../lib/products.js";

function StoreIcon({ product }) {
  const [failed, setFailed] = useState(!product.source_icon);
  const store = product.marketplace || "Store";

  if (failed) {
    return (
      <span className="store-icon store-icon-fallback" aria-hidden="true">
        {store.trim().charAt(0).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      className="store-icon"
      src={product.source_icon}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

// Glasses and watches are tried on by placing the product's own photo, which
// only looks right with a clean photo (a front view for glasses), so the
// photo is checked before the button is shown.
function useAccessoryReady(product, enabled) {
  const [ready, setReady] = useState(false);
  const accessory = enabled && canTryOnAccessory(product);

  useEffect(() => {
    if (!accessory) return undefined;
    let active = true;
    loadOverlay(product).then(
      () => active && setReady(true),
      () => active && setReady(false)
    );
    return () => {
      active = false;
    };
  }, [accessory, product]);

  return accessory && ready;
}

const DEAL_ICONS = { high: "alert", fake: "alert", real: "check" };

// pick: { picked, onPick } on a Budget look planner piece's listings.
// similar: { state: "like" | null, onLike, onNot } to re-order the results around this listing.
export default function ProductCard({ product, isSaved, onToggleSave, onTryOn, onCompleteLook, highlight, deal, pick, similar }) {
  const [imageFailed, setImageFailed] = useState(!product.image_url);
  const accessoryReady = useAccessoryReady(product, Boolean(onTryOn));
  // A short burst on the heart or a ring of the bell when tapped on.
  const [pop, setPop] = useState(null);
  useEffect(() => {
    if (!pop) return undefined;
    const timer = setTimeout(() => setPop(null), 700);
    return () => clearTimeout(timer);
  }, [pop]);
  const suits = usePalette()?.suitsYou(product);
  const compare = useCompare();
  const watch = usePriceWatch();
  const watching = watch?.isWatching(product) ?? false;
  const canWatch = watch && getNumericPrice(product) !== null && product.product_url;
  const comparing = compare?.isSelected(product) ?? false;

  const match = getMatchLevel(product);
  const availability = getAvailability(product);
  const price = formatPrice(product);
  const store = product.marketplace || "Online store";
  const name = product.name || "Unnamed product";
  // Google Shopping results link to Google's page listing the stores.
  const isShopping = product.result_type === "shopping";

  return (
    <article className={`card ${pick?.picked ? "is-picked" : ""}`}>
      <div className="card-media">
        {imageFailed ? (
          <div className="card-media-fallback" role="img" aria-label="Image unavailable">
            <Icon name="image" size={28} />
          </div>
        ) : (
          <img
            src={product.image_url}
            alt={name}
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        )}

        <div className="card-badges">
          {pick?.picked && (
            <span className="badge badge-accent">
              <Icon name="check" size={12} />
              In your look
            </span>
          )}
          {product.condition && (
            <span className="badge badge-condition">
              {product.condition === "used" ? "Used" : "Refurbished"}
            </span>
          )}
          {highlight && (
            <span className="badge badge-accent">
              <Icon name="tag" size={12} />
              {highlight}
            </span>
          )}
          {suits && (
            <span className="badge badge-suits" title={`${suits.name} is one of your colours`}>
              <span className="swatch" style={{ background: suits.hex }} aria-hidden="true" />
              Suits you
            </span>
          )}
          {match && (
            <span
              className={`badge badge-glass match-${match.key}`}
              title="How closely this listing's photo resembles yours"
            >
              <span className="match-dot" />
              {match.label}
            </span>
          )}
        </div>

        {onTryOn && (accessoryReady || (!product.ar_category && canTryOn(product))) && (
          <button
            type="button"
            className="tryon-button"
            onClick={() => onTryOn(product)}
            title="See it on your photo"
          >
            <Icon name="shirt" size={14} />
            Try on
          </button>
        )}

        {canWatch && (
          <button
            type="button"
            className={`watch-button ${watching ? "is-watching" : ""} ${pop === "watch" ? "is-popping" : ""}`}
            onClick={() => {
              if (!watching) setPop("watch");
              watch.toggle(product);
            }}
            aria-pressed={watching}
            disabled={!watching && watch.isFull}
            aria-label={watching ? "Stop watching the price" : "Watch the price"}
            title={
              watching
                ? "Watching the price: you'll see it here when it drops"
                : watch.isFull
                  ? "You're watching the most products allowed (20)"
                  : "Watch the price and get told when it drops"
            }
          >
            <Icon name="bell" size={16} />
          </button>
        )}

        <button
          type="button"
          className={`save-button ${isSaved ? "is-saved" : ""} ${pop === "save" ? "is-popping" : ""}`}
          onClick={() => {
            if (!isSaved) setPop("save");
            onToggleSave(product);
          }}
          aria-pressed={isSaved}
          aria-label={isSaved ? "Remove from saved" : "Save item"}
          title={isSaved ? "Remove from saved" : "Save item"}
        >
          <Icon name="heart" size={17} />
        </button>
      </div>

      <div className="card-body">
        <div className="card-store">
          <StoreIcon product={product} />
          <span>{store}</span>
          {product.multiple_sources && <span className="more-stores">+ more stores</span>}
        </div>

        <h3 className="card-title" title={name}>
          {name}
        </h3>

        {product.rating ? (
          <div className="card-rating" aria-label={`Rated ${product.rating} out of 5`}>
            <span className="star" aria-hidden="true">★</span>
            {Number(product.rating).toFixed(1)}
            {product.reviews ? (
              <span className="reviews">({Number(product.reviews).toLocaleString("en-IN")})</span>
            ) : null}
          </div>
        ) : null}

        <div className="card-meta">
          {price ? (
            <span className="card-price">
              {price}
              {product.original_price_text && (
                <s className="card-original-price" aria-label={`was ${product.original_price_text}`}>
                  {product.original_price_text}
                </s>
              )}
            </span>
          ) : product.pending ? (
            <span className="card-price is-missing is-pending">Checking price…</span>
          ) : (
            <span className="card-price is-missing">Price on store</span>
          )}

          {isShopping && availability === "unknown" ? null : product.pending &&
            availability === "unknown" ? (
            <span className="stock stock-pending">Checking stock</span>
          ) : (
            <span className={`stock stock-${availability}`}>
              {AVAILABILITY_LABELS[availability]}
            </span>
          )}
        </div>

        {product.dupe_savings > 0 ? (
          <p className="deal deal-dupe" title={`The closest matches cost about ${formatAmount(product.dupe_reference_price)}`}>
            <Icon name="trendDown" size={13} />
            <span>
              <strong>Save {formatAmount(product.dupe_savings)}</strong>
              {product.visual_similarity_score != null &&
                ` · looks ${Math.round(product.visual_similarity_score * 100)}% similar`}
            </span>
          </p>
        ) : deal ? (
          <p className={`deal deal-${deal.tone}`} title={deal.title}>
            <Icon name={DEAL_ICONS[deal.tone] || "tag"} size={13} />
            <span>
              <strong>{deal.label}</strong> · {deal.detail}
            </span>
          </p>
        ) : null}

        {product.product_url ? (
          <a
            className="button button-secondary card-cta"
            href={product.product_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {isShopping ? "Compare offers" : "View on store"}
            <Icon name="external" size={15} />
          </a>
        ) : (
          <span className="button button-secondary card-cta is-disabled" aria-disabled="true">
            Link unavailable
          </span>
        )}

        {pick && !pick.picked && (
          <button type="button" className="button button-ghost button-sm card-pick" onClick={pick.onPick}>
            <Icon name="check" size={14} />
            Use in my look
          </button>
        )}

        {similar && product.image_url && (
          <div className="card-similar">
            <button
              type="button"
              className={`card-look ${similar.state === "like" ? "is-active" : ""}`}
              onClick={similar.onLike}
              aria-pressed={similar.state === "like"}
              title="Show the listings that look most like this one first"
            >
              <Icon name="scan" size={13} />
              More like this
            </button>
            <button
              type="button"
              className="card-look"
              onClick={similar.onNot}
              title="Hide this one and push look-alikes down"
            >
              <Icon name="x" size={13} />
              Not this
            </button>
          </div>
        )}

        {(compare || (onCompleteLook && product.name)) && (
          <div className="card-extras">
            {compare && (
              <label className={`card-compare ${comparing ? "is-checked" : ""}`}>
                <input
                  type="checkbox"
                  checked={comparing}
                  disabled={!comparing && compare.isFull}
                  onChange={() => compare.toggle(product)}
                />
                {comparing ? "Comparing" : "Compare"}
              </label>
            )}
            {onCompleteLook && product.name && (
              <button
                type="button"
                className="card-look"
                onClick={() => onCompleteLook(product)}
                title="AI suggests what goes with this, with shopping options"
              >
                <Icon name="sparkles" size={13} />
                Complete look
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export function ProductCardSkeleton() {
  return (
    <div className="card card-skeleton" aria-hidden="true">
      <div className="card-media shimmer" />
      <div className="card-body">
        <span className="skeleton-line shimmer" style={{ width: "40%" }} />
        <span className="skeleton-line shimmer" style={{ width: "92%" }} />
        <span className="skeleton-line shimmer" style={{ width: "70%" }} />
        <span className="skeleton-line skeleton-price shimmer" style={{ width: "35%" }} />
        <span className="skeleton-button shimmer" />
      </div>
    </div>
  );
}
