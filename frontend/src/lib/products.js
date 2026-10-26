export const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const MAX_IMAGE_SIZE = 8 * 1024 * 1024;
export const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export const AVAILABILITY_LABELS = {
  in_stock: "In stock",
  out_of_stock: "Out of stock",
  unknown: "Stock unknown",
};

export const DEFAULT_FILTERS = {
  text: "",
  maxPrice: "",
  minMatch: "any",
  store: "all",
  sort: "relevance",
  myColours: false,
};

export function getProductId(product) {
  return (
    product.id ||
    product.product_id ||
    product.product_url ||
    `${product.name}-${product.marketplace}`
  );
}

export function getNumericPrice(product) {
  if (typeof product.price === "number") return product.price;

  if (typeof product.price === "string") {
    const parsed = Number(product.price.replace(/[^0-9.]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

export function formatAmount(amount, currency = "INR") {
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `₹${amount.toLocaleString("en-IN")}`;
  }
}

/** Display price, or null when the store did not expose one. */
export function formatPrice(product) {
  if (product.price_text) {
    // Google marks some prices with a trailing "*"; drop it for display.
    return String(product.price_text).replace(/\*+$/, "").trim();
  }

  const price = getNumericPrice(product);
  return price === null ? null : formatAmount(price, product.currency || "INR");
}

// CLIP similarity is not a percentage: even unrelated products of the same
// kind score around 0.7. Thresholds calibrated on real searches:
//   ~0.95  the same item (often the same photo)
//   0.80+  a similar-looking product
//   <0.78  same kind of product, clearly different look
export const MATCH_LEVELS = [
  { key: "close", label: "Very close", minScore: 0.88, rank: 3 },
  { key: "similar", label: "Similar", minScore: 0.78, rank: 2 },
  { key: "related", label: "Related", minScore: -Infinity, rank: 1 },
];

/** Raw CLIP similarity for sorting, or null when it was not scored. */
export function getMatchScore(product) {
  const score = Number(product.visual_similarity_score);
  return product.visual_similarity_score == null || !Number.isFinite(score)
    ? null
    : score;
}

/** Visual match level ({key, label, rank}), or null when not scored. */
export function getMatchLevel(product) {
  const score = getMatchScore(product);
  if (score === null) return null;
  return MATCH_LEVELS.find((level) => score >= level.minScore);
}

export function getAvailability(product) {
  return AVAILABILITY_LABELS[product.availability]
    ? product.availability
    : "unknown";
}

export function hasActiveFilters(filters) {
  return Object.keys(DEFAULT_FILTERS).some(
    (key) => filters[key] !== DEFAULT_FILTERS[key]
  );
}

// suitsYou: optional (product) => palette colour or null ("My colours" filter).
export function applyFilters(products, filters, suitsYou) {
  const query = filters.text.trim().toLowerCase();
  const budget = filters.maxPrice === "" ? null : Number(filters.maxPrice);
  const minimumRank =
    MATCH_LEVELS.find((level) => level.key === filters.minMatch)?.rank ?? 0;

  const filtered = products.filter((product) => {
    if (
      query &&
      ![product.name, product.marketplace]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query)
    ) {
      return false;
    }

    if (budget !== null && Number.isFinite(budget)) {
      const price = getNumericPrice(product);
      if (price === null || price > budget) return false;
    }

    if (minimumRank > 0) {
      const level = getMatchLevel(product);
      if (!level || level.rank < minimumRank) return false;
    }

    if (filters.store !== "all" && product.marketplace !== filters.store) {
      return false;
    }

    if (filters.myColours && suitsYou && !suitsYou(product)) {
      return false;
    }

    return true;
  });

  const byPrice = (a, b, direction) => {
    const priceA = getNumericPrice(a);
    const priceB = getNumericPrice(b);
    if (priceA === null && priceB === null) return 0;
    if (priceA === null) return 1;
    if (priceB === null) return -1;
    return direction * (priceA - priceB);
  };

  switch (filters.sort) {
    case "price-low":
      return filtered.sort((a, b) => byPrice(a, b, 1));
    case "price-high":
      return filtered.sort((a, b) => byPrice(a, b, -1));
    case "match":
      return filtered.sort(
        (a, b) => (getMatchScore(b) ?? -1) - (getMatchScore(a) ?? -1)
      );
    default:
      return filtered;
  }
}

// Wakes the server (and loads its image model) while the visitor is still
// choosing a photo, so their first search is not a cold start. Costs no search credit.
export function warmUpServer() {
  fetch(`${API_URL}/api/v1/ping`).catch(() => {});
}
