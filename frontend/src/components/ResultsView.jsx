import { useMemo, useState } from "react";
import Icon from "./Icon.jsx";
import { formatTimeAgo } from "../lib/history.js";
import ProductCard, { ProductCardSkeleton } from "./ProductCard.jsx";
import { fetchSimilarity, reorderByRefs } from "../lib/similar.js";
import { computeDeals } from "../lib/deals.js";
import { usePalette } from "../lib/palette.js";
import {
  DEFAULT_FILTERS,
  applyFilters,
  formatAmount,
  getAvailability,
  getNumericPrice,
  getProductId,
  hasActiveFilters,
} from "../lib/products.js";

function Toolbar({ filters, onChange, stores, shownCount, totalCount, hasMatchScores, hasPalette }) {
  const set = (key) => (event) => onChange({ ...filters, [key]: event.target.value });
  const active = hasActiveFilters(filters);

  return (
    <div className="toolbar" role="search">
      <label className="field field-search">
        <Icon name="search" size={16} />
        <input
          type="search"
          value={filters.text}
          onChange={set("text")}
          placeholder="Filter by name or store"
          aria-label="Filter by name or store"
        />
      </label>

      <label className="field field-price">
        <span aria-hidden="true">₹</span>
        <input
          type="number"
          min="0"
          inputMode="numeric"
          value={filters.maxPrice}
          onChange={set("maxPrice")}
          placeholder="Max price"
          aria-label="Maximum price in rupees"
        />
      </label>

      <select className="field" value={filters.store} onChange={set("store")} aria-label="Store">
        <option value="all">All stores</option>
        {stores.map((store) => (
          <option key={store} value={store}>
            {store}
          </option>
        ))}
      </select>

      {hasMatchScores && (
        <select className="field" value={filters.minMatch} onChange={set("minMatch")} aria-label="Minimum visual match">
          <option value="any">Any match</option>
          <option value="similar">Similar or closer</option>
          <option value="close">Very close only</option>
        </select>
      )}

      <select className="field" value={filters.sort} onChange={set("sort")} aria-label="Sort by">
        <option value="relevance">Sort: Recommended</option>
        {hasMatchScores && <option value="match">Sort: Best match</option>}
        <option value="price-low">Sort: Price, low to high</option>
        <option value="price-high">Sort: Price, high to low</option>
      </select>

      {hasPalette && (
        <button
          type="button"
          className={`field colours-toggle ${filters.myColours ? "is-active" : ""}`}
          aria-pressed={filters.myColours}
          onClick={() => onChange({ ...filters, myColours: !filters.myColours })}
          title="Show only listings in the colours that suit you"
        >
          <Icon name="palette" size={15} />
          My colours
        </button>
      )}

      <div className="toolbar-end">
        <span className="toolbar-count">
          {active ? `${shownCount} of ${totalCount}` : `${totalCount} listings`}
        </span>
        {active && (
          <button type="button" className="button button-ghost button-sm" onClick={() => onChange(DEFAULT_FILTERS)}>
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

function Section({ icon, title, subtitle, products, savedIds, onToggleSave, onTryOn, onCompleteLook, highlightFirst, deals, similarFor, className = "" }) {
  if (!products.length) return null;

  return (
    <section className={`result-section ${className}`}>
      <header className="section-header">
        <span className="section-icon">
          <Icon name={icon} size={18} />
        </span>
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <span className="count-pill">{products.length}</span>
      </header>

      <div className="product-grid">
        {products.map((product, index) => (
          <ProductCard
            key={getProductId(product) || index}
            product={product}
            isSaved={savedIds.has(getProductId(product))}
            onToggleSave={onToggleSave}
            onTryOn={onTryOn}
            onCompleteLook={onCompleteLook}
            highlight={highlightFirst && index === 0 ? highlightFirst : null}
            deal={deals?.get(getProductId(product))}
            similar={similarFor?.(product)}
          />
        ))}
      </div>
    </section>
  );
}

export function ResultsLoading() {
  return (
    <section className="results container" aria-busy="true" aria-label="Loading results">
      <div className="results-header">
        <div>
          <span className="eyebrow">Results</span>
          <span className="skeleton-line skeleton-heading shimmer" />
        </div>
      </div>
      <div className="product-grid">
        {Array.from({ length: 8 }, (_, index) => (
          <ProductCardSkeleton key={index} />
        ))}
      </div>
    </section>
  );
}

function RefineForm({ query, onSubmit, onCancel }) {
  const [text, setText] = useState(query || "");
  const trimmed = text.trim();

  return (
    <form
      className="refine-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed) onSubmit(trimmed);
      }}
    >
      <label className="field refine-field">
        <Icon name="search" size={16} />
        <input
          autoFocus
          value={text}
          maxLength={150}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => event.key === "Escape" && onCancel()}
          placeholder="e.g. Casio G-Shock MTG-B3000 green"
          aria-label="Describe the product"
        />
      </label>
      <button type="submit" className="button button-primary" disabled={!trimmed}>
        Search
      </button>
      <button type="button" className="button button-ghost" onClick={onCancel}>
        Cancel
      </button>
      <p className="refine-hint">
        Add a brand, model or colour. We'll search your photo again with these
        words — this counts as a new search.
      </p>
    </form>
  );
}

function RestoredBanner({ restoredAt, onSearchAgain }) {
  const [now] = useState(() => Date.now());

  return (
    <div className="updating-banner restored-banner" role="status">
      <Icon name="refresh" size={16} />
      <span>
        Saved results from {formatTimeAgo(restoredAt, now)}. Prices and stock
        may have changed.
      </span>
      <button type="button" className="button button-secondary button-sm" onClick={onSearchAgain}>
        Search again
      </button>
    </div>
  );
}

export default function ResultsView({
  isUpdating,
  restoredAt,
  onSearchAgain,
  onRefine,
  kind = "photo",
  query,
  understood,
  bestMatches,
  cheapest,
  dupes = [],
  filters,
  onFiltersChange,
  savedIds,
  onToggleSave,
  onTryOn,
  onCompleteLook,
}) {
  const [isRefining, setIsRefining] = useState(false);
  // Listings the visitor picked ("More like this" / "Not this"), each with how
  // much every listing photo looks like it. Free: no search credit is used.
  const [refs, setRefs] = useState([]);
  const [likeBusy, setLikeBusy] = useState(false);
  const [likeError, setLikeError] = useState("");

  const allProducts = useMemo(() => {
    const unique = new Map();
    [...bestMatches, ...cheapest].forEach((product) =>
      unique.set(getProductId(product), product)
    );
    return [...unique.values()];
  }, [bestMatches, cheapest]);

  // A new search starts over.
  const [refsQuery, setRefsQuery] = useState(query);
  if (refsQuery !== query) {
    setRefsQuery(query);
    setRefs([]);
    setLikeError("");
  }

  async function pick(product, kind) {
    if (likeBusy) return;
    // Tapping "More like this" again takes the pick back.
    if (kind === "like" && refs.some((ref) => ref.imageUrl === product.image_url && ref.kind === "like")) {
      setRefs((current) => current.filter((ref) => ref.imageUrl !== product.image_url));
      return;
    }
    setLikeBusy(true);
    setLikeError("");
    try {
      const scores = await fetchSimilarity(
        product.image_url,
        allProducts.map((item) => item.image_url)
      );
      setRefs((current) => [
        ...current.filter((ref) => ref.imageUrl !== product.image_url),
        { imageUrl: product.image_url, name: product.name, kind, scores },
      ]);
    } catch (error) {
      setLikeError(error.message);
    } finally {
      setLikeBusy(false);
    }
  }

  const similarFor = (product) => ({
    state: refs.find((ref) => ref.imageUrl === product.image_url)?.kind === "like" ? "like" : null,
    onLike: () => pick(product, "like"),
    onNot: () => pick(product, "not"),
  });

  const stores = useMemo(
    () =>
      [...new Set(allProducts.map((product) => product.marketplace).filter(Boolean))].sort(
        (a, b) => a.localeCompare(b)
      ),
    [allProducts]
  );

  const stats = useMemo(() => {
    const priced = allProducts
      .map((product) => ({ product, price: getNumericPrice(product) }))
      .filter((entry) => entry.price !== null);
    const lowest = priced.sort((a, b) => a.price - b.price)[0];

    return {
      lowest: lowest
        ? formatAmount(lowest.price, lowest.product.currency || "INR")
        : "—",
      inStock: allProducts.filter((product) => getAvailability(product) === "in_stock").length,
      stores: new Set(allProducts.map((product) => product.marketplace)).size,
      hasMatchScores: allProducts.some((product) => product.visual_similarity_score != null),
    };
  }, [allProducts]);

  const palette = usePalette();
  const suitsYou = palette?.suitsYou;

  // Deal score compares each price with the typical price of this search.
  const deals = useMemo(() => computeDeals(allProducts), [allProducts]);
  const filteredDupes = useMemo(() => applyFilters(dupes, filters, suitsYou), [dupes, filters, suitsYou]);

  const filteredBest = useMemo(
    () => reorderByRefs(applyFilters(bestMatches, filters, suitsYou), refs),
    [bestMatches, filters, suitsYou, refs]
  );
  const filteredCheapest = useMemo(
    () => reorderByRefs(applyFilters(cheapest, filters, suitsYou), refs),
    [cheapest, filters, suitsYou, refs]
  );
  const shownCount = new Set(
    [...filteredBest, ...filteredCheapest].map(getProductId)
  ).size;

  const cheapestFirst = filteredCheapest[0];
  const showBestPrice =
    filters.sort === "relevance" &&
    cheapestFirst &&
    getAvailability(cheapestFirst) !== "out_of_stock";

  return (
    <section className="results container">
      <div className="results-header">
        <div className="results-title">
          <span className="results-kicker">{kind === "text" ? "Results for" : "Matches for your photo"}</span>
          {isRefining ? (
            <RefineForm
              query={query}
              onCancel={() => setIsRefining(false)}
              onSubmit={(text) => {
                setIsRefining(false);
                onRefine(text);
              }}
            />
          ) : (
            <h2>
              {/* Typed searches are shown exactly as written ("boAt", "iPhone"). */}
              {query ? <span className="results-query">{query}</span> : "Matching products"}
              {onRefine && !isUpdating && (
                <button
                  type="button"
                  className="button button-ghost button-sm refine-button"
                  onClick={() => setIsRefining(true)}
                >
                  <Icon name="pencil" size={14} />
                  {kind === "text" ? "Edit search" : query ? "Not quite? Refine" : "Describe it"}
                </button>
              )}
            </h2>
          )}
          <p className="results-meta">
            {allProducts.length} listing{allProducts.length === 1 ? "" : "s"}
            {stats.lowest && stats.lowest !== "—" ? ` · from ${stats.lowest}` : ""}
            {kind === "text"
              ? ` · ${stats.stores} store${stats.stores === 1 ? "" : "s"}`
              : ` · ${stats.inStock} in stock`}
          </p>
          {understood?.length > 0 && !isRefining && (
            <ul className="understood" aria-label="Your search was understood as">
              <li className="understood-label">
                <Icon name="sparkles" size={13} />
                Understood as
              </li>
              {understood.map((part) => (
                <li key={part} className="understood-chip">
                  {part}
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>

      {restoredAt && !isUpdating && (
        <RestoredBanner restoredAt={restoredAt} onSearchAgain={onSearchAgain} />
      )}

      {isUpdating && (
        <div className="updating-banner" role="status">
          <span className="spinner" />
          Checking prices and stock at each store — listings will update in a moment.
        </div>
      )}

      {(refs.length > 0 || likeBusy || likeError) && (
        <div className="updating-banner like-banner" role="status">
          {likeBusy ? <span className="spinner" /> : <Icon name="scan" size={16} />}
          <span>
            {likeError ||
              (likeBusy
                ? "Comparing the photos…"
                : `Re-ordered by your picks (${refs.filter((r) => r.kind === "like").length} liked, ${refs.filter((r) => r.kind === "not").length} hidden).`)}
          </span>
          {refs.length > 0 && (
            <button
              type="button"
              className="button button-secondary button-sm"
              onClick={() => {
                setRefs([]);
                setLikeError("");
              }}
            >
              Back to original order
            </button>
          )}
        </div>
      )}

      <Toolbar
        filters={filters}
        onChange={onFiltersChange}
        stores={stores}
        shownCount={shownCount}
        totalCount={allProducts.length}
        hasMatchScores={stats.hasMatchScores}
        hasPalette={Boolean(palette)}
      />

      {shownCount === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">
            <Icon name="search" size={22} />
          </span>
          <h3>No listings match these filters</h3>
          <p>Try a higher price limit or a different store.</p>
          <button type="button" className="button button-secondary" onClick={() => onFiltersChange(DEFAULT_FILTERS)}>
            Reset filters
          </button>
        </div>
      ) : (
        <>
          <Section
            icon={kind === "text" ? "search" : "scan"}
            title={kind === "text" ? "Top results" : "Best matches"}
            subtitle={
              kind === "text"
                ? "The most relevant listings for your search."
                : "Listings that look most like your photo."
            }
            products={filteredBest}
            similarFor={similarFor}
            savedIds={savedIds}
            onToggleSave={onToggleSave}
            onTryOn={onTryOn}
            onCompleteLook={onCompleteLook}
            deals={deals}
          />
          <Section
            className="dupes-section"
            icon="sparkles"
            title="Cheaper lookalikes"
            subtitle="Dupes: listings that look like the closest matches but cost much less."
            products={filteredDupes}
            savedIds={savedIds}
            onToggleSave={onToggleSave}
            onTryOn={onTryOn}
            onCompleteLook={onCompleteLook}
          />
          <Section
            icon="tag"
            title="Lowest prices"
            subtitle={
              kind === "text"
                ? "The cheapest listings that match your search."
                : "The cheapest listings we found, in-stock items first."
            }
            products={filteredCheapest}
            similarFor={similarFor}
            savedIds={savedIds}
            onToggleSave={onToggleSave}
            onTryOn={onTryOn}
            onCompleteLook={onCompleteLook}
            deals={deals}
            highlightFirst={showBestPrice ? "Best price" : null}
          />
        </>
      )}
    </section>
  );
}
