import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";
import { compareProducts } from "../lib/assistant.js";
import { formatPrice, getProductId } from "../lib/products.js";

/** The products picked for comparison, at the bottom of the screen. */
export function CompareBar({ products, onCompare, onAsk, onRemove, onClear }) {
  if (!products.length) return null;
  const ready = products.length >= 2;

  return (
    <div className="compare-bar" role="region" aria-label="Products to compare">
      <div className="compare-bar-items">
        {products.map((product) => (
          <span key={getProductId(product)} className="compare-chip">
            {product.image_url && <img src={product.image_url} alt="" />}
            <span className="compare-chip-name" title={product.name}>
              {product.name}
            </span>
            <button type="button" onClick={() => onRemove(product)} aria-label={`Remove ${product.name}`}>
              <Icon name="x" size={13} />
            </button>
          </span>
        ))}
      </div>
      <span className="compare-bar-hint">{ready ? `${products.length} selected` : "Pick one more to compare"}</span>
      <button type="button" className="button button-ghost button-sm" onClick={onClear}>
        Clear
      </button>
      {onAsk && (
        <button type="button" className="button button-secondary button-sm" onClick={onAsk} disabled={!ready}>
          <Icon name="heart" size={15} />
          Ask my family
        </button>
      )}
      <button type="button" className="button button-primary button-sm" onClick={onCompare} disabled={!ready}>
        <Icon name="layers" size={15} />
        Compare
      </button>
    </div>
  );
}

function Rating({ product }) {
  if (!product.rating) return <span className="compare-muted">No rating</span>;
  return (
    <span>
      ★ {Number(product.rating).toFixed(1)}
      {product.reviews ? (
        <span className="compare-muted"> ({Number(product.reviews).toLocaleString("en-IN")})</span>
      ) : null}
    </span>
  );
}

/**
 * Side by side: photo, price, store and rating for each product, then the
 * features AI reads from their names, their strong points and a verdict.
 */
export default function CompareDialog({ products, query, onClose }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    compareProducts(products, query).then(
      (answer) => active && setResult(answer),
      (compareError) =>
        active &&
        setError(
          compareError instanceof TypeError
            ? "Can't reach the Vistora server. Check that the backend is running."
            : compareError.message
        )
    );
    return () => {
      active = false;
    };
  }, [products, query]);

  useEffect(() => {
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const best = result?.best ?? null;
  const columns = { gridTemplateColumns: `140px repeat(${products.length}, minmax(0, 1fr))` };

  return (
    <div className="modal-backdrop" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal compare-modal" role="dialog" aria-modal="true" aria-labelledby="compare-title">
        <header className="modal-header">
          <div>
            <h2 id="compare-title">
              <Icon name="layers" size={18} /> Compare
            </h2>
            <p>Side by side, with AI reading the details from each listing.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="compare-body">
          {result && (
            <div className="compare-verdict">
              <span className="chat-avatar" aria-hidden="true">
                <Icon name="sparkles" size={16} />
              </span>
              <p>{result.verdict}</p>
            </div>
          )}
          {!result && !error && (
            <p className="compare-loading">
              <span className="spinner" /> AI is comparing them…
            </p>
          )}
          {error && (
            <div className="alert alert-error" role="alert">
              <Icon name="alert" size={17} />
              <span>{error}</span>
            </div>
          )}

          <div className="compare-table" role="table" aria-label="Product comparison">
            <div className="compare-row compare-head" role="row" style={columns}>
              <span role="rowheader" />
              {products.map((product, index) => (
                <div key={getProductId(product)} role="cell" className={`compare-product ${best === index ? "is-best" : ""}`}>
                  {best === index && (
                    <span className="badge badge-accent compare-best">
                      <Icon name="check" size={12} /> Best pick
                    </span>
                  )}
                  {product.image_url ? (
                    <img src={product.image_url} alt="" />
                  ) : (
                    <span className="compare-noimage" aria-hidden="true">
                      <Icon name="image" size={22} />
                    </span>
                  )}
                  <strong title={product.name}>{product.name}</strong>
                </div>
              ))}
            </div>

            <div className="compare-row" role="row" style={columns}>
              <span role="rowheader">Price</span>
              {products.map((product) => (
                <span key={getProductId(product)} role="cell" className="compare-price">
                  {formatPrice(product) || <span className="compare-muted">Not listed</span>}
                </span>
              ))}
            </div>
            <div className="compare-row" role="row" style={columns}>
              <span role="rowheader">Store</span>
              {products.map((product) => (
                <span key={getProductId(product)} role="cell">{product.marketplace || "—"}</span>
              ))}
            </div>
            <div className="compare-row" role="row" style={columns}>
              <span role="rowheader">Rating</span>
              {products.map((product) => (
                <span key={getProductId(product)} role="cell">
                  <Rating product={product} />
                </span>
              ))}
            </div>

            {result?.attributes.map((attribute) => (
              <div key={attribute.name} className="compare-row" role="row" style={columns}>
                <span role="rowheader">{attribute.name}</span>
                {attribute.values.map((value, index) => (
                  <span key={index} role="cell" className={value === "not listed" ? "compare-muted" : ""}>
                    {value}
                  </span>
                ))}
              </div>
            ))}

            {result?.pros.some((list) => list.length) && (
              <div className="compare-row" role="row" style={columns}>
                <span role="rowheader">Strong points</span>
                {result.pros.map((list, index) => (
                  <ul key={index} role="cell" className="compare-pros">
                    {list.map((pro) => (
                      <li key={pro}>
                        <Icon name="check" size={13} />
                        {pro}
                      </li>
                    ))}
                  </ul>
                ))}
              </div>
            )}

            <div className="compare-row" role="row" style={columns}>
              <span role="rowheader" />
              {products.map((product) => (
                <span key={getProductId(product)} role="cell">
                  {product.product_url && (
                    <a
                      className="button button-secondary button-sm"
                      href={product.product_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View on store
                      <Icon name="external" size={13} />
                    </a>
                  )}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
