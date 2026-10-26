import { API_URL, getNumericPrice } from "./products.js";

const VOTER_KEY = "vistora-voter";

// A random id for this browser, so each person gets one vote they can change.
export function voterId() {
  try {
    const saved = localStorage.getItem(VOTER_KEY);
    if (saved) return saved;
  } catch {
    // Private mode: fall through to a fresh id for this visit.
  }
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  const id = `v-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  try {
    localStorage.setItem(VOTER_KEY, id);
  } catch {
    // The id still works for this visit.
  }
  return id;
}

async function request(path, options) {
  const response = await fetch(`${API_URL}${path}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Something went wrong. Please try again.");
  return body;
}

const json = (data) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

/** Saves 2-4 products as a board; resolves with its id. */
export async function createBoard(products, title) {
  const items = products.map((product) => ({
    name: product.name,
    price: getNumericPrice(product),
    store: product.marketplace,
    image_url: product.image_url,
    url: product.product_url,
  }));
  return (await request("/api/v1/boards", json({ title, items }))).id;
}

export const fetchBoard = (id) =>
  request(`/api/v1/boards/${encodeURIComponent(id)}?voter=${encodeURIComponent(voterId())}`);

export const castVote = (id, option) =>
  request(`/api/v1/boards/${encodeURIComponent(id)}/vote`, json({ voter: voterId(), option }));

export const boardUrl = (id) => `${window.location.origin}/?board=${encodeURIComponent(id)}`;

/** A WhatsApp link with the message already typed; opens the contact picker. */
export function whatsappLink(url, title) {
  const text = `${title || "Which one should I buy?"} Tap to see the options and vote: ${url}`;
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

/** The board id in the page address (/?board=<id>), or "". */
export function boardIdFromAddress() {
  return new URLSearchParams(window.location.search).get("board") || "";
}
