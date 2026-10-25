import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import CropDialog from "./components/CropDialog.jsx";
import Icon, { Logo } from "./components/Icon.jsx";
import Landing from "./components/Landing.jsx";
import ProductCard from "./components/ProductCard.jsx";
import RecentSearches from "./components/RecentSearches.jsx";
import HomeSearch from "./components/HomeSearch.jsx";
import ToolGrid from "./components/ToolGrid.jsx";
import Emoji3D from "./components/Emoji3D.jsx";
import { HeroBackdrop, StoreMarquee } from "./components/HeroDecor.jsx";
import { resetPointer, trackPointer, useTheme } from "./lib/motion.js";
import { TOOLS } from "./lib/tools.js";
import TryOnDialog from "./components/TryOnDialog.jsx";
import AccessoryTryOnDialog from "./components/AccessoryTryOnDialog.jsx";
import SearchQuota from "./components/SearchQuota.jsx";
import OutfitView from "./components/OutfitView.jsx";
import ResultsView, { ResultsLoading } from "./components/ResultsView.jsx";
import UploadPanel from "./components/UploadPanel.jsx";
import {
  addToHistory,
  dataUrlToFile,
  makeThumbnail,
  readHistory,
  writeHistory,
} from "./lib/history.js";
import { cropToFile, prepareForUpload } from "./lib/resizeImage.js";
import {
  streamGifts,
  streamList,
  streamLook,
  streamOutfit,
  streamPlan,
  streamRating,
  streamRoom,
  streamSearch,
  streamTextSearch,
} from "./lib/searchStream.js";
import CompareDialog, { CompareBar } from "./components/CompareDialog.jsx";
import PlanPanel from "./components/PlanPanel.jsx";
import GiftPanel from "./components/GiftPanel.jsx";
import PriceWatch from "./components/PriceWatch.jsx";
import {
  MAX_WATCHES,
  PriceWatchContext,
  applyResults,
  askToNotify,
  checkWatches,
  dueWatches,
  newWatch,
  notifyDrops,
  readWatches,
  writeWatches,
} from "./lib/priceWatch.js";
import { CompareContext, MAX_COMPARE } from "./lib/compare.js";
import AssistantChat from "./components/AssistantChat.jsx";
import ColoursDialog from "./components/ColoursDialog.jsx";
import { PaletteContext, paletteMatcher, readPalette, writePalette } from "./lib/palette.js";
import {
  ALLOWED_IMAGE_TYPES,
  DEFAULT_FILTERS,
  MAX_IMAGE_SIZE,
  formatAmount,
  getNumericPrice,
  getProductId,
} from "./lib/products.js";

const SAVED_KEY = "vistora-wishlist";
const PROGRESS_FINISH_MS = 250;

function readSaved() {
  try {
    const saved = localStorage.getItem(SAVED_KEY);
    const parsed = saved ? JSON.parse(saved) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// Tools whose input is a photo, and the purpose each sets on the photo page.
const PHOTO_TOOLS = { photo: "product", outfit: "outfit", rate: "rate", room: "room", list: "list" };
const PURPOSE_TOOLS = Object.fromEntries(Object.entries(PHOTO_TOOLS).map(([tool, purpose]) => [purpose, tool]));

// The footer's links to every tool.
const FOOTER_LINKS = [
  { title: "Shop", keys: ["photo", "list", "plan", "gift"] },
  { title: "Style", keys: ["outfit", "rate", "colours", "tryon"] },
  { title: "More", keys: ["room", "watch"] },
];

// Try it on: example searches whose results can be tried on.
const TRY_ON_EXAMPLES = [
  { query: "Cotton kurti for women", art: "dress", label: "Clothes", text: "A kurti, shirt or dress on your photo (AI, about 30 s)" },
  { query: "Aviator sunglasses for men", art: "sunglasses", label: "Sunglasses", text: "The real frames placed on your face photo" },
  { query: "Analog watch for men", art: "watch", label: "Watches", text: "The real watch placed on your wrist photo" },
];

// Search stages reported by the backend, in order (see UploadPanel).
const STAGE = { uploading: 0, identifying: 1, ranking: 2, checking: 3 };

// kind: "photo" (Google Lens + CLIP) or "text" (Google Shopping).
function toResults(data, kind = "photo") {
  return {
    kind,
    query: data.online_search_query || "",
    understood: Array.isArray(data.understood) ? data.understood : null,
    bestMatches: Array.isArray(data.best_matches) ? data.best_matches : [],
    cheapest: Array.isArray(data.cheapest_alternatives) ? data.cheapest_alternatives : [],
    dupes: Array.isArray(data.dupes) ? data.dupes : [],
  };
}

// Listings shown to the shopping assistant: a few per outfit item, so every
// item is covered.
const CHAT_PRODUCTS_PER_ITEM = 4;

function uniqueProducts(products) {
  const unique = new Map();
  products.forEach((product) => unique.set(getProductId(product), product));
  return [...unique.values()];
}

// Preview listings can be "pending" (price or stock still being checked).
function clearPending(results) {
  if (!results) return results;
  const settle = (products) => products.map((product) => ({ ...product, pending: false }));
  return { ...results, bestMatches: settle(results.bestMatches), cheapest: settle(results.cheapest) };
}

export default function App() {
  const resultsRef = useRef(null);

  const [view, setView] = useState("discover");
  // The tool page open (null = home with the search box and every tool),
  // and what the photo is for on the photo page.
  const [tool, setTool] = useState(null);
  const [theme, toggleTheme] = useTheme();
  const [purpose, setPurpose] = useState("product");
  const [tryOnProduct, setTryOnProduct] = useState(null);
  const [textQuery, setTextQuery] = useState("");
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  // The uploaded photo before any crop, so a crop can be redone or undone.
  const [originalFile, setOriginalFile] = useState(null);
  const [originalUrl, setOriginalUrl] = useState("");
  const [isCropping, setIsCropping] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stage, setStage] = useState(STAGE.uploading);
  const [stageElapsed, setStageElapsed] = useState(0);
  const [identifiedQuery, setIdentifiedQuery] = useState("");
  const stageRef = useRef(STAGE.uploading);
  const stageStartedAtRef = useRef(0);
  const scrolledRef = useRef(false);
  // The running photo/text search, so a newer one can cancel it.
  const searchAbortRef = useRef(null);
  const [error, setError] = useState("");

  const [results, setResults] = useState(null);
  // Find the outfit: { gender, items, photoUrl } while shown.
  const [outfit, setOutfit] = useState(null);
  const [isFindingOutfit, setIsFindingOutfit] = useState(false);
  // What to go back to: the results a "Complete the look" was opened
  // from ({ results, filters }), or the outfit an "Exact match" search
  // was started from ({ outfit }).
  const [returnTo, setReturnTo] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [saved, setSaved] = useState(readSaved);
  // "Colours that suit you": the palette from a selfie, kept in this browser.
  const [palette, setPalette] = useState(readPalette);
  const [showColours, setShowColours] = useState(false);
  // Price watch: watched products (kept in this browser), the latest drops
  // and whether a check is running.
  const [watches, setWatches] = useState(readWatches);
  const [drops, setDrops] = useState([]);
  const [isCheckingPrices, setIsCheckingPrices] = useState(false);
  const [watchError, setWatchError] = useState("");
  const watchValue = useMemo(() => {
    const ids = new Set(watches.map((watch) => watch.id));
    return {
      isWatching: (product) => ids.has(getProductId(product)),
      isFull: watches.length >= MAX_WATCHES,
      toggle: (product) => {
        const id = getProductId(product);
        if (!ids.has(id)) askToNotify();
        setWatches((current) =>
          current.some((watch) => watch.id === id)
            ? current.filter((watch) => watch.id !== id)
            : current.length < MAX_WATCHES
              ? [...current, newWatch(product)]
              : current
        );
      },
    };
  }, [watches]);

  // Products picked to compare, and the ones being compared in the dialog.
  const [compareList, setCompareList] = useState([]);
  const [comparing, setComparing] = useState(null);
  const compareValue = useMemo(() => {
    const ids = new Set(compareList.map(getProductId));
    return {
      isSelected: (product) => ids.has(getProductId(product)),
      isFull: compareList.length >= MAX_COMPARE,
      toggle: (product) =>
        setCompareList((current) =>
          current.some((item) => getProductId(item) === getProductId(product))
            ? current.filter((item) => getProductId(item) !== getProductId(product))
            : current.length < MAX_COMPARE
              ? [...current, product]
              : current
        ),
    };
  }, [compareList]);
  const paletteValue = useMemo(
    () => (palette ? { ...palette, suitsYou: paletteMatcher(palette) } : null),
    [palette]
  );
  const [history, setHistory] = useState(readHistory);

  const savedIds = useMemo(() => new Set(saved.map(getProductId)), [saved]);

  // What the shopping assistant can see, and a key that changes with it.
  const chat = useMemo(() => {
    if (results) {
      return {
        key: `results:${results.kind}:${results.query}:${results.restoredAt || ""}`,
        query: results.query,
        products: uniqueProducts([...results.bestMatches, ...results.dupes, ...results.cheapest]),
      };
    }
    if (outfit?.items.length && !outfit.items.some((item) => item.pending)) {
      return {
        key: `outfit:${outfit.product?.name || outfit.photoUrl}`,
        query: outfit.items.map((item) => item.description).join(", "),
        products: uniqueProducts(
          outfit.items.flatMap((item) =>
            [...(item.best_matches || []), ...(item.cheapest_alternatives || [])].slice(
              0,
              CHAT_PRODUCTS_PER_ITEM
            )
          )
        ),
      };
    }
    return null;
  }, [results, outfit]);

  useEffect(() => {
    try {
      localStorage.setItem(SAVED_KEY, JSON.stringify(saved));
    } catch {
      // Saved items remain available for this session.
    }
  }, [saved]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      if (originalUrl) URL.revokeObjectURL(originalUrl);
    };
  }, [originalUrl]);

  useEffect(() => {
    writeHistory(history);
  }, [history]);

  useEffect(() => {
    writeWatches(watches);
  }, [watches]);

  // Re-check watched prices: those due (every 12 hours) when the app opens,
  // or all of them from "Check now".
  const checkPrices = useCallback(async (all) => {
    const current = readWatches();
    const toCheck = all ? current : dueWatches(current);
    if (!toCheck.length) return;
    setIsCheckingPrices(true);
    setWatchError("");
    try {
      const results = await checkWatches(toCheck);
      const { watches: updated, drops: found } = applyResults(readWatches(), results);
      setWatches(updated);
      if (found.length) {
        setDrops(found);
        notifyDrops(found);
      }
    } catch (checkError) {
      if (all) setWatchError(checkError instanceof TypeError ? "Can't reach the Vistora server." : checkError.message);
    } finally {
      setIsCheckingPrices(false);
    }
  }, []);

  useEffect(() => {
    // Once, shortly after the app opens.
    const timer = setTimeout(() => checkPrices(false), 1500);
    return () => clearTimeout(timer);
  }, [checkPrices]);

  // Drive the progress steps while a search is running.
  useEffect(() => {
    if (!isSearching) return undefined;

    const startedAt = Date.now();
    const timer = setInterval(() => {
      const now = Date.now();
      setElapsed((now - startedAt) / 1000);
      setStageElapsed((now - stageStartedAtRef.current) / 1000);
    }, 250);
    return () => clearInterval(timer);
  }, [isSearching]);

  // Bring results into view the first time they appear for a search.
  useEffect(() => {
    if ((results || outfit) && !scrolledRef.current) {
      scrolledRef.current = true;
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [results, outfit]);

  function advanceStage(next) {
    if (next <= stageRef.current) return;
    stageRef.current = next;
    stageStartedAtRef.current = Date.now();
    setStage(next);
    setStageElapsed(0);
  }

  function selectImage(nextFile) {
    if (!nextFile) return;

    if (!ALLOWED_IMAGE_TYPES.includes(nextFile.type)) {
      setError("Please choose a JPG, PNG or WebP image.");
      return;
    }

    if (nextFile.size > MAX_IMAGE_SIZE) {
      setError("This image is larger than 8 MB. Please choose a smaller one.");
      return;
    }

    setError("");
    if (tool !== "photo") {
      setTool("photo");
      setPurpose("product");
    }
    setOriginalFile(nextFile);
    setOriginalUrl(URL.createObjectURL(nextFile));
    showImage(nextFile);
    setView("discover");
  }

  // Use a (possibly cropped) image for the next search.
  function showImage(nextFile) {
    setFile(nextFile);
    setPreviewUrl(URL.createObjectURL(nextFile));
    setResults(null);
    setOutfit(null);
    setReturnTo(null);
    setFilters(DEFAULT_FILTERS);
  }

  function applyCrop(croppedFile) {
    setIsCropping(false);
    showImage(croppedFile);
  }

  function undoCrop() {
    if (originalFile) showImage(originalFile);
  }

  const closeCrop = useCallback(() => setIsCropping(false), []);
  const closeTryOn = useCallback(() => setTryOnProduct(null), []);
  const closeColours = useCallback(() => setShowColours(false), []);
  const closeCompare = useCallback(() => setComparing(null), []);

  // Reopen a recent search: its photo and results, without searching again.
  function openRecent(entry) {
    setError("");
    setFilters(DEFAULT_FILTERS);
    setView("discover");
    scrolledRef.current = false;

    if (entry.kind === "text") {
      setTool(null);
      setTextQuery(entry.query);
      setResults({ ...entry.results, kind: "text", restoredAt: entry.savedAt });
      return;
    }

    const restored = dataUrlToFile(entry.image, entry.fileName);

    setTool("photo");
    setPurpose("product");
    setOriginalFile(restored);
    setOriginalUrl(URL.createObjectURL(restored));
    setFile(restored);
    setPreviewUrl(URL.createObjectURL(restored));
    setResults({ ...entry.results, kind: "photo", restoredAt: entry.savedAt });
  }

  function rememberTextSearch(finalResults) {
    setHistory((current) =>
      addToHistory(current, {
        id: String(Date.now()),
        kind: "text",
        query: finalResults.query,
        image: null,
        savedAt: Date.now(),
        results: finalResults,
      })
    );
  }


  function rememberSearch(searchedFile, finalResults) {
    const entry = {
      id: String(Date.now()),
      kind: "photo",
      query: finalResults.query,
      fileName: searchedFile.name,
      savedAt: Date.now(),
      results: finalResults,
    };

    makeThumbnail(searchedFile)
      .then((image) => setHistory((current) => addToHistory(current, { ...entry, image })))
      .catch(() => {
        // History is a convenience; skip it if the photo can't be read.
      });
  }

  function removeImage() {
    setFile(null);
    setPreviewUrl("");
    setOriginalFile(null);
    setOriginalUrl("");
    setResults(null);
    setOutfit(null);
    setReturnTo(null);
    setFilters(DEFAULT_FILTERS);
    setError("");
  }

  // Allow pasting an image from the clipboard.
  useEffect(() => {
    function handlePaste(event) {
      if (isSearching) return;
      const item = [...(event.clipboardData?.items || [])].find((entry) =>
        entry.type.startsWith("image/")
      );
      const pasted = item?.getAsFile();
      if (pasted) {
        event.preventDefault();
        selectImage(pasted);
      }
    }

    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  });

  function toggleSaved(product) {
    const id = getProductId(product);
    setSaved((current) =>
      current.some((item) => getProductId(item) === id)
        ? current.filter((item) => getProductId(item) !== id)
        : [...current, { ...product, pending: false }]
    );
  }

  // Open a tool from the home page's grid (or a link): photo tools share
  // one page with their purpose set; Price watch is on Saved; Colours is a
  // dialog.
  function openTool(key) {
    setError("");
    if (key === "watch") {
      setView("saved");
    } else if (key === "colours") {
      setShowColours(true);
      return;
    } else {
      setView("discover");
      if (PHOTO_TOOLS[key]) {
        setTool("photo");
        setPurpose(PHOTO_TOOLS[key]);
      } else {
        setTool(key);
      }
      setResults(null);
      setOutfit(null);
      setReturnTo(null);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Back to the home page: the search box and every tool.
  function goHome() {
    setView("discover");
    setTool(null);
    setResults(null);
    setOutfit(null);
    setReturnTo(null);
    setError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Home, scrolled to the list of every tool.
  function goTools() {
    goHome();
    requestAnimationFrame(() =>
      requestAnimationFrame(() => document.querySelector(".tool-hub")?.scrollIntoView({ behavior: "smooth" }))
    );
  }

  // The photo page's main button, for the chosen purpose.
  function runPhoto(chosen) {
    if (chosen === "outfit") findOutfit();
    else if (chosen === "rate") rateOutfit();
    else if (chosen === "room") shopRoom();
    else if (chosen === "list") shopList();
    else search();
  }

  // refineQuery: optional words to narrow the search (from "Refine").
  // itemFile: search this photo instead of the uploaded one (an outfit
  // item's crop), with returnPoint to go back to afterwards.
  async function search(refineQuery, itemFile, returnPoint) {
    const query = typeof refineQuery === "string" ? refineQuery.trim() : "";
    const searchFile = itemFile instanceof File ? itemFile : file;

    if (!searchFile) {
      setError("Please upload a product photo first.");
      return;
    }

    setError("");
    setResults(null);
    setOutfit(null);
    setReturnTo(returnPoint || null);
    setFilters(DEFAULT_FILTERS);
    setElapsed(0);
    setIdentifiedQuery("");
    stageRef.current = STAGE.uploading;
    stageStartedAtRef.current = Date.now();
    setStage(STAGE.uploading);
    setStageElapsed(0);
    scrolledRef.current = false;
    setIsSearching(true);

    searchAbortRef.current?.abort();
    const controller = new AbortController();
    searchAbortRef.current = controller;

    let finalData = null;

    try {
      const upload = await prepareForUpload(searchFile);

      await streamSearch(upload, (event) => {
        switch (event.type) {
          case "stage":
            advanceStage(STAGE.identifying);
            break;
          case "identified":
            setIdentifiedQuery(event.online_search_query || "");
            advanceStage(STAGE.ranking);
            break;
          case "preview":
            // Lens's own order arrives first, then the visually ranked
            // listings; prices and stock fill in with the final results.
            advanceStage(event.ranked === false ? STAGE.ranking : STAGE.checking);
            setResults(toResults(event, "photo"));
            break;
          case "final":
            finalData = event;
            break;
          case "error":
            throw new Error(event.detail || "Search failed. Please try again.");
          default:
            break;
        }
      }, query, controller.signal);

      if (!finalData) {
        throw new Error("The search ended unexpectedly. Please try again.");
      }

      const finalResults = toResults(finalData, "photo");

      if (finalResults.bestMatches.length + finalResults.cheapest.length === 0) {
        setResults(null);
        setError(
          "We couldn't find this product online. Try a clearer photo where the product fills most of the frame."
        );
        return;
      }

      // Let the progress bar finish, then settle the final prices and stock.
      setIsComplete(true);
      await new Promise((resolve) => setTimeout(resolve, PROGRESS_FINISH_MS));
      setResults(finalResults);
      rememberSearch(searchFile, finalResults);
    } catch (searchError) {
      // A newer search cancelled this one; it owns the screen now.
      if (controller.signal.aborted) return;
      // Keep any preview results, but stop showing them as "checking".
      setResults(clearPending);
      setError(
        searchError instanceof TypeError
          ? "Can't reach the Vistora server. Check that the backend is running."
          : searchError.message
      );
    } finally {
      if (searchAbortRef.current === controller) {
        setIsSearching(false);
        setIsComplete(false);
      }
    }
  }

  // Identify everything the person in the photo wears and shop each item.
  async function findOutfit() {
    if (!file) {
      setError("Please upload a photo of the outfit first.");
      return;
    }

    setReturnTo(null);
    await streamItems(
      // Its own URL: the preview's is revoked when another photo is shown,
      // and the outfit can be returned to after an "Exact match" search.
      { kind: "outfit", gender: "", items: [], photoUrl: URL.createObjectURL(file) },
      async (onEvent) => streamOutfit(await prepareForUpload(file), onEvent),
      "Couldn't find the outfit. Please try again."
    );
  }

  // Find the furniture and decor in a room photo and shop each piece.
  async function shopRoom() {
    if (!file) {
      setError("Please upload a photo of the room first.");
      return;
    }

    setReturnTo(null);
    await streamItems(
      { kind: "room", style: "", gender: "", items: [], photoUrl: URL.createObjectURL(file) },
      async (onEvent) => streamRoom(await prepareForUpload(file), onEvent),
      "Couldn't shop this room. Please try again."
    );
  }

  // Six gift ideas with listings: { request, budget }.
  async function findGifts(gift) {
    setReturnTo(null);
    await streamItems(
      { kind: "gift", title: "", recipient: "", budget: gift.budget || 0, gender: "", items: [], photoUrl: "" },
      (onEvent) => streamGifts(gift, onEvent),
      "Couldn't find gift ideas. Please try again."
    );
  }

  // Shop a whole list: a photo of it (the uploaded photo) or typed text.
  async function shopList(list) {
    const fromPhoto = !list?.text;
    if (fromPhoto && !file) {
      setError("Please upload a photo of your list first.");
      return;
    }
    setReturnTo(null);
    await streamItems(
      { kind: "list", title: "", picks: {}, gender: "", items: [], photoUrl: fromPhoto ? URL.createObjectURL(file) : "" },
      async (onEvent) =>
        streamList(fromPhoto ? { file: await prepareForUpload(file) } : { text: list.text }, onEvent),
      "Couldn't shop this list. Please try again."
    );
  }

  // Plan a whole look within a budget: { request, budget, gender }.
  async function planLook(plan) {
    setReturnTo(null);
    await streamItems(
      { kind: "plan", title: "", budget: plan.budget || 0, picks: {}, gender: plan.gender || "", items: [], photoUrl: "" },
      (onEvent) => streamPlan(plan, onEvent),
      "Couldn't plan this look. Please try again."
    );
  }

  // Swap the listing picked for a planned piece.
  function pickForPlan(itemId, key) {
    setOutfit((current) => current && { ...current, picks: { ...current.picks, [itemId]: key } });
  }

  // AI stylist: score the outfit in the photo and shop what would improve it.
  async function rateOutfit() {
    if (!file) {
      setError("Please upload a photo of the outfit first.");
      return;
    }

    setReturnTo(null);
    await streamItems(
      { kind: "rating", rating: null, gender: "", items: [], photoUrl: URL.createObjectURL(file) },
      async (onEvent) =>
        streamRating(
          await prepareForUpload(file),
          onEvent,
          palette?.best.map((colour) => colour.name)
        ),
      "Couldn't rate this outfit. Please try again."
    );
  }

  function savePalette(next) {
    setPalette(next);
    writePalette(next);
    setShowColours(false);
    if (!next) setFilters((current) => ({ ...current, myColours: false }));
  }

  // Suggest what goes with a product and shop each suggestion.
  async function completeLook(product) {
    if (isFindingOutfit || !product?.name) return;

    if (results) setReturnTo({ results, filters });
    setView("discover");
    await streamItems(
      { kind: "look", product, gender: "", items: [], photoUrl: product.image_url || "" },
      (onEvent) => streamLook(product.name, onEvent, getNumericPrice(product)),
      "Couldn't put a look together. Please try again."
    );
  }

  function goBack() {
    if (!returnTo) return;
    setOutfit(returnTo.outfit || null);
    setResults(returnTo.results || null);
    setFilters(returnTo.filters || DEFAULT_FILTERS);
    setReturnTo(null);
    scrolledRef.current = false;
  }

  // Search one outfit item by photo (Google Lens on its crop) for the exact
  // product, keeping the outfit to come back to.
  async function findExactMatch(item) {
    if (!outfit?.photoUrl || !item.box || isSearching) return;

    let itemFile;
    try {
      itemFile = await cropToFile(outfit.photoUrl, item.box, `${item.type || "item"}.jpg`);
    } catch (cropError) {
      setError(cropError.message);
      return;
    }
    const returnPoint = { outfit };
    showImage(itemFile);
    setTool("photo");
    setPurpose("product");
    await search(undefined, itemFile, returnPoint);
  }

  // Show items (an outfit or a look) streamed by start(onEvent): "items",
  // then one "item" event as each item's shopping options arrive.
  async function streamItems(initial, start, failMessage) {
    setError("");
    setResults(null);
    setOutfit(initial);
    scrolledRef.current = false;
    setIsFindingOutfit(true);

    const updateItem = (item) =>
      setOutfit((current) =>
        current && {
          ...current,
          items: current.items.map((existing) =>
            existing.id === item.id ? { ...item, pending: false } : existing
          ),
        }
      );

    try {
      let finished = false;
      await start((event) => {
        switch (event.type) {
          case "rating":
            setOutfit((current) => ({ ...current, rating: event.rating }));
            break;
          case "plan":
            setOutfit((current) => ({ ...current, title: event.title, budget: event.budget, gender: event.gender }));
            break;
          case "gifts":
            setOutfit((current) => ({ ...current, title: event.title, recipient: event.recipient, budget: event.budget }));
            break;
          case "list":
            setOutfit((current) => ({ ...current, title: event.title }));
            break;
          case "items":
            setOutfit((current) => ({
              ...current,
              gender: event.gender,
              items: event.items.map((item) => ({ ...item, pending: true })),
            }));
            break;
          case "item":
            updateItem(event.item);
            break;
          case "final":
            finished = true;
            setOutfit((current) => ({
              ...current,
              rating: event.rating ?? current.rating ?? null,
              // Shop this room's style; the planner's look, budget, picks and total.
              style: event.style ?? current.style,
              title: event.title ?? current.title,
              budget: event.budget ?? current.budget,
              picks: event.picks ?? current.picks,
              recipient: event.recipient ?? current.recipient,
              gender: event.gender,
              items: event.items.map((item) => ({ ...item, pending: false })),
            }));
            break;
          case "error":
            throw new Error(event.detail || failMessage);
          default:
            break;
        }
      });
      if (!finished) throw new Error("The search ended unexpectedly. Please try again.");
    } catch (outfitError) {
      setOutfit((current) =>
        current?.items.length || current?.rating
          ? { ...current, items: current.items.map((item) => ({ ...item, pending: false })) }
          : null
      );
      setError(
        outfitError instanceof TypeError
          ? "Can't reach the Vistora server. Check that the backend is running."
          : outfitError.message
      );
    } finally {
      setIsFindingOutfit(false);
    }
  }

  // Search Google Shopping for a typed description.
  async function searchText(text) {
    const query = (typeof text === "string" ? text : textQuery).trim();

    if (query.length < 2) {
      setError("Type at least 2 characters to search.");
      return;
    }

    setTool(null);
    setView("discover");
    setTextQuery(query);
    setError("");
    setResults(null);
    setOutfit(null);
    setReturnTo(null);
    setFilters(DEFAULT_FILTERS);
    scrolledRef.current = false;
    setIsSearching(true);

    searchAbortRef.current?.abort();
    const controller = new AbortController();
    searchAbortRef.current = controller;

    let finalData = null;

    try {
      await streamTextSearch(query, (event) => {
        if (event.type === "final") finalData = event;
        if (event.type === "error") {
          throw new Error(event.detail || "Search failed. Please try again.");
        }
      }, controller.signal);

      if (!finalData) {
        throw new Error("The search ended unexpectedly. Please try again.");
      }

      const finalResults = toResults(finalData, "text");

      if (finalResults.bestMatches.length + finalResults.cheapest.length === 0) {
        setError(`No products found for "${query}". Try different or fewer words.`);
        return;
      }

      setResults(finalResults);
      rememberTextSearch(finalResults);
    } catch (searchError) {
      // A newer search cancelled this one; it owns the screen now.
      if (controller.signal.aborted) return;
      setError(
        searchError instanceof TypeError
          ? "Can't reach the Vistora server. Check that the backend is running."
          : searchError.message
      );
    } finally {
      if (searchAbortRef.current === controller) setIsSearching(false);
    }
  }

  return (
    <PaletteContext.Provider value={paletteValue}>
    <CompareContext.Provider value={compareValue}>
    <PriceWatchContext.Provider value={watchValue}>
    <div className="app">
      <header className="site-header">
        <div className="container header-inner">
          <button type="button" className="brand" onClick={goHome} aria-label="Vistora home">
            <Logo />
          </button>

          <nav className="nav" aria-label="Main">
            <button
              type="button"
              className={`nav-item ${view === "discover" ? "is-active" : ""}`}
              aria-current={view === "discover" ? "page" : undefined}
              onClick={goHome}
              aria-label="Home"
            >
              <span className="nav-label">Home</span>
            </button>
            <button type="button" className="nav-item" onClick={goTools}>
              <span className="nav-label">Tools</span>
            </button>
            <button
              type="button"
              className={`nav-item nav-colours ${palette ? "has-palette" : ""}`}
              onClick={() => setShowColours(true)}
              title="Find the colours that suit you"
            >
              {palette ? (
                <span className="nav-swatches" aria-hidden="true">
                  {palette.best.slice(0, 3).map((colour) => (
                    <span key={colour.name} style={{ background: colour.hex }} />
                  ))}
                </span>
              ) : (
                <Icon name="palette" size={16} />
              )}
              <span className="nav-label">My colours</span>
            </button>
            <button
              type="button"
              className={`nav-item ${view === "saved" ? "is-active" : ""}`}
              aria-current={view === "saved" ? "page" : undefined}
              onClick={() => setView("saved")}
              aria-label="Saved and watched"
            >
              <Icon name="heart" size={16} />
              <span className="nav-label">Saved</span>
              {saved.length + watches.length > 0 && (
                <span className="nav-count">{saved.length + watches.length}</span>
              )}
            </button>
          </nav>
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title={theme === "dark" ? "Light theme" : "Dark theme"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>
        </div>
      </header>

      <main>
        {drops.length > 0 && (
          <div className="container">
            <div className="drop-banner" role="status">
              <Icon name="trendDown" size={20} />
              <p>
                <strong>
                  {drops.length === 1
                    ? `Price drop: ${drops[0].watch.product.name}`
                    : `${drops.length} products you're watching got cheaper`}
                </strong>
                {" — "}
                {drops.length === 1
                  ? `now ${formatAmount(drops[0].watch.lastPrice)}, ${formatAmount(drops[0].saved)} less.`
                  : `save up to ${formatAmount(Math.max(...drops.map((drop) => drop.saved)))}.`}
              </p>
              <button
                type="button"
                className="button button-secondary button-sm"
                onClick={() => {
                  setView("saved");
                  setDrops([]);
                }}
              >
                See them
              </button>
              <button type="button" className="icon-button" onClick={() => setDrops([])} aria-label="Dismiss">
                <Icon name="x" size={16} />
              </button>
            </div>
          </div>
        )}
        {view === "discover" ? (
          <>
            {tool ? (
              <section className={`tool-page tone-${TOOLS[tool === "photo" ? PURPOSE_TOOLS[purpose] : tool].tone}`}>
                <div className="container tool-page-inner">
                  <button type="button" className="link-button tool-back" onClick={goHome}>
                    <Icon name="undo" size={14} />
                    All tools
                  </button>
                  <header className="tool-page-header">
                    <span className="tool-page-emoji" aria-hidden="true">
                      <Emoji3D name={TOOLS[tool === "photo" ? PURPOSE_TOOLS[purpose] : tool].art} size={46} />
                    </span>
                    <div>
                      <h1>{TOOLS[tool === "photo" ? PURPOSE_TOOLS[purpose] : tool].title}</h1>
                      <p>{TOOLS[tool === "photo" ? PURPOSE_TOOLS[purpose] : tool].text}</p>
                    </div>
                  </header>

                  {tool === "photo" ? (
                    <UploadPanel
                      file={file}
                      previewUrl={previewUrl}
                      isSearching={isSearching}
                      isComplete={isComplete}
                      elapsed={elapsed}
                      stage={stage}
                      stageElapsed={stageElapsed}
                      identifiedQuery={identifiedQuery}
                      error={error}
                      onSelect={selectImage}
                      onRemove={removeImage}
                      isCropped={Boolean(file && originalFile && file !== originalFile)}
                      onCrop={() => setIsCropping(true)}
                      onUndoCrop={undoCrop}
                      purpose={purpose}
                      onPurposeChange={(next) => {
                        setPurpose(next);
                        setError("");
                      }}
                      onRun={runPhoto}
                      isBusy={isFindingOutfit}
                      onTypedList={(text) => shopList({ text })}
                      onOpenTool={openTool}
                    />
                  ) : tool === "gift" ? (
                    <GiftPanel
                      onFind={findGifts}
                      isFinding={isFindingOutfit && outfit?.kind === "gift"}
                      error={error}
                    />
                  ) : tool === "plan" ? (
                    <PlanPanel
                      onPlan={planLook}
                      isPlanning={isFindingOutfit && outfit?.kind === "plan"}
                      error={error}
                    />
                  ) : (
                    <div className="panel search-panel tryon-tool">
                      <p className="tryon-tool-lead">
                        Search for something to wear, then tap <strong>Try on</strong> on its card.
                        Pick a kind to start:
                      </p>
                      <ul className="tryon-tool-options">
                        {TRY_ON_EXAMPLES.map((example) => (
                          <li key={example.query}>
                            <button type="button" className="tool-card" onClick={() => searchText(example.query)}>
                              <span className="tool-card-icon" aria-hidden="true">
                                <Emoji3D name={example.art} size={30} />
                              </span>
                              <span className="tool-card-text">
                                <strong>{example.label}</strong>
                                <small>{example.text}</small>
                              </span>
                              <Icon name="arrowRight" size={16} className="tool-card-arrow" />
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </section>
            ) : (
              <section className="home-hero" onPointerMove={trackPointer} onPointerLeave={resetPointer}>
                <HeroBackdrop />
                <div className="container home-hero-inner">
                  <h1>
                    <span className="hero-line">Find it.</span>
                    <span className="hero-line">
                      <span className="hero-gradient">For less.</span>
                    </span>
                  </h1>
                  <p className="hero-lead">
                    Search with a photo, your words or your voice. Vistora checks every store and
                    shows you where it's cheapest.
                  </p>
                  <HomeSearch
                    query={textQuery}
                    onQueryChange={setTextQuery}
                    onSearch={searchText}
                    onPhoto={selectImage}
                    isSearching={isSearching}
                    error={error}
                  />
                </div>
                <StoreMarquee />
              </section>
            )}

            {!tool && !results && !outfit && !isSearching && <ToolGrid onOpen={openTool} />}

            <div ref={resultsRef} className="results-anchor" />

            {isSearching && !results && <ResultsLoading />}

            {outfit && (
              <OutfitView
                outfit={outfit}
                photoUrl={outfit.photoUrl}
                savedIds={savedIds}
                onToggleSave={toggleSaved}
                onTryOn={setTryOnProduct}
                onMore={searchText}
                onBack={returnTo?.results && !isFindingOutfit ? goBack : null}
                onExactMatch={outfit.kind === "look" || outfit.kind === "plan" || isSearching ? null : findExactMatch}
                onPick={pickForPlan}
              />
            )}

            {results && returnTo?.outfit && !isSearching && (
              <div className="container">
                <button type="button" className="button button-ghost button-sm outfit-back" onClick={goBack}>
                  <Icon name="undo" size={15} />
                  Back to the outfit
                </button>
              </div>
            )}

            {results && (
              <ResultsView
                isUpdating={isSearching}
                restoredAt={results.restoredAt}
                kind={results.kind}
                onSearchAgain={() =>
                  results.kind === "text" ? searchText(results.query) : search()
                }
                onRefine={results.kind === "text" ? searchText : search}
                query={results.query}
                understood={results.understood}
                bestMatches={results.bestMatches}
                dupes={results.dupes}
                cheapest={results.cheapest}
                filters={filters}
                onFiltersChange={setFilters}
                savedIds={savedIds}
                onToggleSave={toggleSaved}
                onTryOn={setTryOnProduct}
                onCompleteLook={completeLook}
              />
            )}

            {chat?.products.length > 0 && !isSearching && (
              <AssistantChat
                key={chat.key}
                products={chat.products}
                query={chat.query}
                onSearch={searchText}
              />
            )}

            {!isSearching && (
              <RecentSearches
                entries={history}
                onOpen={openRecent}
                onRemove={(id) =>
                  setHistory((current) => current.filter((entry) => entry.id !== id))
                }
                onClear={() => setHistory([])}
              />
            )}

            {!tool && !results && !outfit && !isSearching && <Landing />}
          </>
        ) : (
          <section className="saved container">
            <div className="saved-header">
              <div>
                <span className="eyebrow">Your collection</span>
                <h2>Saved and watched</h2>
                <p>Kept in this browser: products you've saved, and prices you're watching.</p>
              </div>
            </div>

            <PriceWatch
              watches={watches}
              onCheck={() => checkPrices(true)}
              isChecking={isCheckingPrices}
              onRemove={(id) => setWatches((current) => current.filter((watch) => watch.id !== id))}
              error={watchError}
            />

            <div className="saved-header">
              <div>
                <h3>Saved items</h3>
              </div>

              {saved.length > 0 && (
                <button type="button" className="button button-ghost button-sm" onClick={() => setSaved([])}>
                  <Icon name="trash" size={15} />
                  Clear all
                </button>
              )}
            </div>

            {saved.length === 0 ? (
              <div className="empty-state">
                <span className="empty-icon">
                  <Icon name="heart" size={22} />
                </span>
                <h3>Nothing saved yet</h3>
                <p>Tap the heart on any product to keep it here.</p>
                <button type="button" className="button button-primary" onClick={goHome}>
                  Start a search
                  <Icon name="arrowRight" size={16} />
                </button>
              </div>
            ) : (
              <div className="product-grid">
                {saved.map((product, index) => (
                  <ProductCard
                    key={getProductId(product) || index}
                    product={product}
                    isSaved
                    onToggleSave={toggleSaved}
                    onTryOn={setTryOnProduct}
                    onCompleteLook={completeLook}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </main>

      {isCropping && originalUrl && (
        <CropDialog
          src={originalUrl}
          fileName={originalFile?.name}
          onApply={applyCrop}
          onCancel={closeCrop}
        />
      )}

      {showColours && (
        <ColoursDialog palette={palette} onSave={savePalette} onClose={closeColours} />
      )}

      {tryOnProduct &&
        (tryOnProduct.ar_category ? (
          <AccessoryTryOnDialog product={tryOnProduct} onClose={closeTryOn} />
        ) : (
          <TryOnDialog product={tryOnProduct} onClose={closeTryOn} />
        ))}

      <footer className="site-footer">
        <div className="container footer-top">
          <div className="footer-brand">
            <Logo />
            <p>Your AI shopping assistant for India. Find it, compare every store, pay less.</p>
            <SearchQuota refreshKey={isSearching} />
          </div>
          {FOOTER_LINKS.map((column) => (
            <nav key={column.title} className="footer-column" aria-label={column.title}>
              <h3>{column.title}</h3>
              <ul>
                {column.keys.map((key) => (
                  <li key={key}>
                    <button type="button" onClick={() => openTool(key)}>
                      {TOOLS[key].title}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="container footer-bottom">
          <p>
            Prices and availability come from third-party stores and may change. Always confirm on
            the seller's site before buying.
          </p>
          <span>© {new Date().getFullYear()} Vistora · Made in India</span>
        </div>
      </footer>
      {/* Phones: app-style navigation at the bottom. */}
      <nav className="tab-bar" aria-label="Main">
        <button
          type="button"
          className={view === "discover" && !tool ? "is-active" : ""}
          onClick={goHome}
        >
          <Icon name="home" size={21} />
          Home
        </button>
        <button type="button" className={tool ? "is-active" : ""} onClick={goTools}>
          <Icon name="grid" size={21} />
          Tools
        </button>
        <button type="button" className={view === "saved" ? "is-active" : ""} onClick={() => setView("saved")}>
          <Icon name="heart" size={21} />
          Saved
          {saved.length + watches.length > 0 && <span className="tab-count">{saved.length + watches.length}</span>}
        </button>
        <button type="button" onClick={() => setShowColours(true)}>
          <Icon name="palette" size={21} />
          Colours
        </button>
      </nav>

      {comparing && (
        <CompareDialog products={comparing} query={results?.query || ""} onClose={closeCompare} />
      )}

      <CompareBar
        products={compareList}
        onCompare={() => setComparing(compareList)}
        onRemove={compareValue.toggle}
        onClear={() => setCompareList([])}
      />
    </div>
    </PriceWatchContext.Provider>
    </CompareContext.Provider>
    </PaletteContext.Provider>
  );
}
