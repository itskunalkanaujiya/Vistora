import { API_URL } from "./products.js";

const MAX_IMAGES = 40;

// How much each listing photo looks like the reference listing's photo:
// { [imageUrl]: similarity }. Costs no search credit.
export async function fetchSimilarity(referenceUrl, imageUrls) {
  const images = [...new Set(imageUrls.filter(Boolean))].slice(0, MAX_IMAGES);
  const response = await fetch(`${API_URL}/api/v1/products/similar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reference: referenceUrl, images }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Couldn't re-order the results. Please try again.");
  }
  return (await response.json()).scores || {};
}

// Re-orders listings around the ones the visitor picked: "like" refs pull
// similar-looking listings up, "not" refs hide that listing and push its
// look-alikes down. Listings without a readable photo keep their place at the end.
export function reorderByRefs(products, refs) {
  if (!refs.length) return products;

  const hidden = new Set(refs.filter((ref) => ref.kind === "not").map((ref) => ref.imageUrl));
  const visible = products.filter((product) => !hidden.has(product.image_url));

  const scored = [];
  const unscored = [];
  visible.forEach((product, index) => {
    const scores = refs.map((ref) =>
      ref.imageUrl === product.image_url ? 1 : ref.scores[product.image_url]
    );
    if (scores.every((score) => score === undefined)) {
      unscored.push(product);
      return;
    }
    const total = refs.reduce(
      (sum, ref, i) => sum + (ref.kind === "like" ? 1 : -1) * (scores[i] ?? 0),
      0
    );
    scored.push({ product, total, index });
  });

  scored.sort((a, b) => b.total - a.total || a.index - b.index);
  return [...scored.map((entry) => entry.product), ...unscored];
}
