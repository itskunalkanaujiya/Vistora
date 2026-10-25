import { API_URL } from "./products.js";

// Photo try-on for glasses and watches: MediaPipe finds the eyes or wrist in
// the person's photo, in the browser, and the product's real photo (cut out
// of its background by the backend) is drawn on top. The person's photo
// isn't uploaded.

// Keep in sync with the @mediapipe/tasks-vision version in package.json.
const WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";
const MODEL_URLS = {
  glasses:
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
  watch:
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
};

// Face mesh points: iris centres, with the eye corners as a fallback.
const FACE = {
  irises: [468, 473],
  eyes: [[33, 133], [263, 362]],
  sides: [127, 356],
  // The nose tip, and a point on each cheek where the light is read.
  nose: 1,
  cheeks: [205, 425],
};
// How far a turned head is allowed to change the frame's perspective.
const MAX_YAW = 0.3;
// Distance between lens centres relative to the distance between pupils
// (frames are a little wider than the eyes), and how far the lens centre
// sits below the pupil, as a share of the pupil distance.
const LENS_SPREAD = 1.18;
const LENS_DROP = 0.06;
// The whole frame is about as wide as the face at the temples.
export const FACE_FILL = 0.95;
// How far the pupil-based size may differ from the face-based one.
const SIZE_AGREEMENT = 0.12;
// Product photos checked at the same time, and their results.
const MAX_CHECKS = 4;
const overlays = new Map();
const queue = [];
let running = 0;
// Hand points: wrist, index / middle / pinky knuckles.
const HAND = { wrist: 0, index: 5, middle: 9, pinky: 17 };

const MAX_STRAP_RATIO = 2.4; // longest strap shown, relative to watch width

/**
 * Combine the two size estimates for glasses: the face-based one, nudged
 * towards the pupil-based one by at most SIZE_AGREEMENT.
 */
export function frameScale(pupilScale, faceScale) {
  if (!faceScale || !Number.isFinite(faceScale)) return pupilScale;
  const ratio = Math.min(1 + SIZE_AGREEMENT, Math.max(1 - SIZE_AGREEMENT, pupilScale / faceScale));
  return faceScale * ratio;
}

// The person's photo is kept in this browser per kind of product (a face
// for glasses, a wrist for watches) so it can be reused.
const PHOTO_KEYS = { glasses: "vistora-tryon-face", watch: "vistora-tryon-wrist" };

export function readAccessoryPhoto(category) {
  try {
    return localStorage.getItem(PHOTO_KEYS[category]) || "";
  } catch {
    return "";
  }
}

export function saveAccessoryPhoto(category, dataUrl) {
  try {
    localStorage.setItem(PHOTO_KEYS[category], dataUrl);
  } catch {
    // Storage full or blocked: the photo still works for this visit.
  }
}

export function forgetAccessoryPhoto(category) {
  try {
    localStorage.removeItem(PHOTO_KEYS[category]);
  } catch {
    // Nothing to forget.
  }
}

export function canTryOnAccessory(product) {
  return Boolean(product?.ar_category && (product.tryon_image_url || product.image_url));
}

function runQueued(task) {
  return new Promise((resolve, reject) => {
    queue.push({ task, resolve, reject });
    pump();
  });
}

function pump() {
  while (running < MAX_CHECKS && queue.length) {
    const { task, resolve, reject } = queue.shift();
    running += 1;
    task()
      .then(resolve, reject)
      .finally(() => {
        running -= 1;
        pump();
      });
  }
}

/**
 * The product photo with its background removed: { image, centres }, where
 * centres are the lens centres for glasses ([lx, ly, rx, ry] as fractions).
 * Shared between the card (which checks the photo is usable) and the dialog.
 */
export function loadOverlay(product) {
  const key = `${product.ar_category}|${product.tryon_image_url || product.image_url}`;
  if (!overlays.has(key)) {
    const promise = runQueued(() => fetchOverlay(product));
    // A failed connection may work later; a refused photo won't.
    promise.catch((error) => {
      if (error instanceof TypeError) overlays.delete(key);
    });
    overlays.set(key, promise);
  }
  return overlays.get(key);
}

async function fetchOverlay(product) {
  const params = new URLSearchParams({
    url: product.tryon_image_url || product.image_url,
    category: product.ar_category,
  });
  const response = await fetch(`${API_URL}/api/v1/tryon/overlay?${params}`);

  if (!response.ok) {
    let detail = "Couldn't prepare this product's photo. Try another listing.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the default message.
    }
    throw new Error(detail);
  }
  const centres = response.headers.get("X-Lens-Centres")?.split(",").map(Number) || null;
  const image = await createImageBitmap(await response.blob());
  return { image, centres };
}

/** Load the face (glasses) or hand (watch) tracker. */
export async function createTracker(category) {
  const vision = await import("@mediapipe/tasks-vision");
  const fileset = await vision.FilesetResolver.forVisionTasks(WASM_URL);
  const Task = category === "glasses" ? vision.FaceLandmarker : vision.HandLandmarker;
  const extra = category === "glasses" ? { numFaces: 1 } : { numHands: 1 };

  // The GPU is faster but not available everywhere; fall back to the CPU.
  for (const delegate of ["GPU", "CPU"]) {
    try {
      return await Task.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URLS[category], delegate },
        runningMode: "IMAGE",
        ...extra,
      });
    } catch (error) {
      if (delegate === "CPU") throw error;
    }
  }
  return null;
}

/** Landmarks of the first face or hand in a photo, or null. */
export function detect(tracker, source) {
  const result = tracker.detect(source);
  return (result.faceLandmarks || result.landmarks || [])[0] || null;
}

function point(landmarks, index, width, height, mirror) {
  const { x, y } = landmarks[index];
  return { x: (mirror ? 1 - x : x) * width, y: y * height };
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function average(points) {
  return {
    x: points.reduce((sum, p) => sum + p.x, 0) / points.length,
    y: points.reduce((sum, p) => sum + p.y, 0) / points.length,
  };
}

/**
 * Where to draw the product: centre, width (px) and rotation (radians).
 * `size` scales the product and `lift` moves it along the face or arm.
 */
export function placement(category, landmarks, width, height, mirror, { size, lift }) {
  const at = (index) => point(landmarks, index, width, height, mirror);

  if (category === "glasses") {
    let [left, right] =
      landmarks.length > FACE.irises[1]
        ? FACE.irises.map(at)
        : FACE.eyes.map((corners) => average(corners.map(at)));
    if (right.x < left.x) [left, right] = [right, left];

    const pupils = distance(left, right);
    const faceWidth = distance(at(FACE.sides[0]), at(FACE.sides[1]));
    const angle = Math.atan2(right.y - left.y, right.x - left.x);
    const middle = average([left, right]);
    // Down the nose, perpendicular to the eyes; `lift` moves the frame up.
    const shift = (LENS_DROP - lift * 0.3) * pupils;

    // How far the head is turned: the nose tip against the middle of the face.
    const sides = FACE.sides.map(at);
    const faceMiddle = average(sides);
    const nose = landmarks.length > FACE.nose ? at(FACE.nose) : faceMiddle;
    const yaw = faceWidth ? (nose.x - faceMiddle.x) / faceWidth : 0;
    const cheeks = landmarks.length > FACE.cheeks[1] ? FACE.cheeks.map(at) : null;
    return {
      x: middle.x - Math.sin(angle) * shift,
      y: middle.y + Math.cos(angle) * shift,
      // For glasses, width is the distance between the lens centres.
      width: pupils * LENS_SPREAD * size,
      faceWidth: faceWidth * size,
      angle,
      yaw: Number.isFinite(yaw) ? Math.max(-MAX_YAW, Math.min(MAX_YAW, yaw)) : 0,
      cheeks,
    };
  }

  const wrist = at(HAND.wrist);
  const middle = at(HAND.middle);
  const handLength = distance(wrist, middle);
  const palmWidth = distance(at(HAND.index), at(HAND.pinky));
  const towardFingers = {
    x: (middle.x - wrist.x) / (handLength || 1),
    y: (middle.y - wrist.y) / (handLength || 1),
  };
  // Watches sit a little way down the forearm from the wrist joint.
  const offset = handLength * (0.22 - lift * 0.2);
  return {
    x: wrist.x - towardFingers.x * offset,
    y: wrist.y - towardFingers.y * offset,
    // The palm looks narrow when the hand turns sideways; keep a minimum.
    width: Math.max(palmWidth, handLength * 0.55) * 0.9 * size,
    // Turn the photo so the strap runs along the arm.
    angle: Math.atan2(towardFingers.y, towardFingers.x) + Math.PI / 2,
  };
}

/**
 * A soft shadow under the product, as if it rests on the skin; it makes
 * glasses look worn rather than pasted on.
 */
export function addShadow(context, productWidth) {
  context.shadowColor = "rgba(0, 0, 0, 0.35)";
  context.shadowBlur = Math.max(4, productWidth * 0.035);
  context.shadowOffsetY = Math.max(2, productWidth * 0.012);
}

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

// Typical brightness of a well-lit face; photos darker or lighter than this
// darken or lighten the frame to match.
const REFERENCE_SKIN_LUMA = 150;

function canvasOf(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.ceil(width));
  canvas.height = Math.max(1, Math.ceil(height));
  return canvas;
}

/** Average brightness of the photo around a point, or null if unreadable. */
function patchLuma(context, centre, radius) {
  try {
    const x = Math.max(0, Math.round(centre.x - radius));
    const y = Math.max(0, Math.round(centre.y - radius));
    const size = Math.max(2, Math.round(radius * 2));
    const { data } = context.getImageData(x, y, size, size);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }
    return sum / (data.length / 4);
  } catch {
    return null;
  }
}

/** Where the light comes from and how bright the face is, read from the cheeks. */
function readLight(context, place, width) {
  if (!place.cheeks) return { lean: 0, skin: null };
  const radius = Math.max(3, width * 0.04);
  const left = patchLuma(context, place.cheeks[0], radius);
  const right = patchLuma(context, place.cheeks[1], radius);
  if (left === null || right === null) return { lean: 0, skin: null };
  return { lean: clamp((right - left) / (left + right + 1), -0.35, 0.35), skin: (left + right) / 2 };
}

/**
 * The frame as a layer of its own, drawn in two halves either side of the
 * bridge so a turned head shows the far lens narrower than the near one, with
 * a soft sheen across the lenses and the temple ends fading as they go behind
 * the ears. Returns { layer, anchorX, anchorY } (the lens midpoint in the layer).
 */
function frameLayer(overlay, centres, scale, yaw) {
  const [leftX, leftY, rightX, rightY] = centres;
  const bridge = ((leftX + rightX) / 2) * overlay.width;
  // The nose pointing right (yaw > 0) means the right side is the far side.
  const nearScale = 1 + yaw * 0.9;
  const farScale = 1 - yaw * 0.9;
  const leftWidth = bridge * scale * nearScale;
  const rightWidth = (overlay.width - bridge) * scale * farScale;
  const height = overlay.height * scale;

  const layer = canvasOf(leftWidth + rightWidth, height);
  const context = layer.getContext("2d");
  context.imageSmoothingQuality = "high";
  // A pixel of overlap hides the seam at the bridge.
  context.drawImage(overlay, 0, 0, bridge + 1, overlay.height, 0, 0, leftWidth + 1, height);
  context.drawImage(overlay, bridge, 0, overlay.width - bridge, overlay.height, leftWidth, 0, rightWidth, height);

  // A soft sheen over the lenses and rims breaks up the flat, printed look.
  context.globalCompositeOperation = "source-atop";
  const sheen = context.createLinearGradient(0, 0, layer.width, layer.height);
  sheen.addColorStop(0, "rgba(255, 255, 255, 0.2)");
  sheen.addColorStop(0.45, "rgba(255, 255, 255, 0.04)");
  sheen.addColorStop(1, "rgba(255, 255, 255, 0)");
  context.fillStyle = sheen;
  context.fillRect(0, 0, layer.width, layer.height);

  // The ends of the temples tuck behind the ears.
  context.globalCompositeOperation = "destination-in";
  const ends = context.createLinearGradient(0, 0, layer.width, 0);
  ends.addColorStop(0, "rgba(0, 0, 0, 0.3)");
  ends.addColorStop(0.07, "rgba(0, 0, 0, 1)");
  ends.addColorStop(0.93, "rgba(0, 0, 0, 1)");
  ends.addColorStop(1, "rgba(0, 0, 0, 0.3)");
  context.fillStyle = ends;
  context.fillRect(0, 0, layer.width, layer.height);

  return { layer, anchorX: leftWidth, anchorY: ((leftY + rightY) / 2) * overlay.height * scale };
}

/** A dark copy of a layer's shape, for the shadow the frame casts on the face. */
function shadowOf(layer) {
  const shadow = canvasOf(layer.width, layer.height);
  const context = shadow.getContext("2d");
  context.drawImage(layer, 0, 0);
  context.globalCompositeOperation = "source-in";
  context.fillStyle = "rgb(28, 16, 12)";
  context.fillRect(0, 0, shadow.width, shadow.height);
  return shadow;
}

function drawGlasses(context, overlay, centres, place) {
  const [leftX, , rightX] = centres;
  const scale = frameScale(
    place.width / ((rightX - leftX) * overlay.width),
    place.faceWidth ? (place.faceWidth * FACE_FILL) / overlay.width : null
  );
  const width = overlay.width * scale;
  const { layer, anchorX, anchorY } = frameLayer(overlay, centres, scale, place.yaw || 0);
  const { lean, skin } = readLight(context, place, width);
  const hasFilter = "filter" in context;

  context.save();
  context.translate(place.x, place.y);
  context.rotate(place.angle);

  if (hasFilter) {
    const shadow = shadowOf(layer);
    // The light's side moves the shadow to the other side of the frame.
    const dx = -lean * width * 0.18;
    // A wide, soft shadow as the frame stands off the face, and a tight one
    // where the rims and nose pads touch the skin.
    context.globalAlpha = 0.3;
    context.filter = `blur(${Math.max(2, width * 0.03)}px)`;
    context.drawImage(shadow, -anchorX + dx, -anchorY + width * 0.03);
    context.globalAlpha = 0.28;
    context.filter = `blur(${Math.max(1, width * 0.008)}px)`;
    context.drawImage(shadow, -anchorX + dx * 0.3, -anchorY + width * 0.009);
    context.globalAlpha = 1;
    // Match the photo's exposure.
    const exposure = skin === null ? 1 : clamp(Math.sqrt(skin / REFERENCE_SKIN_LUMA), 0.78, 1.08);
    context.filter = `brightness(${(exposure * 0.94).toFixed(3)}) contrast(1.14) saturate(1.12)`;
  } else {
    addShadow(context, width);
  }

  context.drawImage(layer, -anchorX, -anchorY);
  context.restore();
}

/** Draw the product photo ({ image, centres }) at a placement. */
export function drawProduct(context, { image: overlay, centres }, category, place) {
  if (category === "glasses" && centres) {
    drawGlasses(context, overlay, centres, place);
    return;
  }

  let source = { x: 0, y: 0, width: overlay.width, height: overlay.height };
  let turn = 0;

  if (category === "watch") {
    // Photos with the strap running sideways are turned upright.
    if (overlay.width > overlay.height * 1.25) turn = Math.PI / 2;
    // Very long straps are cropped to the part around the dial.
    const across = turn ? source.height : source.width;
    const along = turn ? source.width : source.height;
    const maxAlong = across * MAX_STRAP_RATIO;
    if (along > maxAlong) {
      const cut = (along - maxAlong) / 2;
      source = turn
        ? { x: cut, y: 0, width: maxAlong, height: source.height }
        : { x: 0, y: cut, width: source.width, height: maxAlong };
    }
  }

  const across = turn ? source.height : source.width;
  const scale = place.width / across;
  const drawWidth = source.width * scale;
  const drawHeight = source.height * scale;

  context.save();
  context.translate(place.x, place.y);
  context.rotate(place.angle + turn);
  context.drawImage(
    overlay,
    source.x,
    source.y,
    source.width,
    source.height,
    -drawWidth / 2,
    -drawHeight / 2,
    drawWidth,
    drawHeight
  );
  context.restore();
}
