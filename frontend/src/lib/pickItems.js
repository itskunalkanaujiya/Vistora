import { API_URL } from "./products.js";

// The products in a photo, each with a box (fractions of the photo): { items }.
// Nothing is searched; the visitor taps the one they want.
export async function fetchPhotoItems(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_URL}/api/v1/photo/items`, { method: "POST", body: formData });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Couldn't scan this photo. Please try again.");
  }
  return response.json();
}
