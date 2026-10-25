import { useEffect, useState } from "react";
import { API_URL } from "../lib/products.js";

const LOW_SHARE = 0.1; // warn when this share of the month's searches is left
const LOW_COUNT = 25; // warn for one-time credits below this many searches

function formatRenewal(date) {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function level(left, total) {
  if (left <= 0) return "empty";
  if (total ? left / total <= LOW_SHARE : left <= LOW_COUNT) return "low";
  return "ok";
}

function QuotaRow({ label, left, total, note, title }) {
  const state = level(left, total);
  return (
    <div className={`search-quota-row quota-${state}`} title={title}>
      <div className="search-quota-head">
        <span>
          {label && <span className="search-quota-label">{label}</span>}
          <strong>{left.toLocaleString("en-IN")}</strong>
          {total ? ` of ${total.toLocaleString("en-IN")}` : ""} left
        </span>
        {note && <span className="search-quota-renew">{note}</span>}
      </div>
      {total ? (
        <div
          className="search-quota-track"
          role="meter"
          aria-label={`${label || "Searches"} left`}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={left}
        >
          <span style={{ width: `${Math.max(0, Math.min(1, left / total)) * 100}%` }} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * Searches left: photo search uses SearchApi.io credits first when set up
 * (faster), then SerpApi (monthly plan); text search uses Serper.dev credits
 * when set up. Read again whenever `refreshKey` changes
 * (after each search). Renders nothing if the counts can't be read.
 */
export default function SearchQuota({ refreshKey }) {
  const [usage, setUsage] = useState(null);

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/api/v1/usage`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => active && setUsage(data))
      .catch(() => active && setUsage(null));
    return () => {
      active = false;
    };
  }, [refreshKey]);

  if (!usage || typeof usage.searches_left !== "number" || !usage.searches_per_month) {
    return null;
  }

  const renewal = usage.renews_on ? formatRenewal(usage.renews_on) : "";
  const text = usage.text && typeof usage.text.searches_left === "number" ? usage.text : null;
  const fast =
    usage.fast_photo && typeof usage.fast_photo.searches_left === "number" ? usage.fast_photo : null;
  const photoEmpty = usage.searches_left <= 0;
  const textEmpty = text ? text.searches_left <= 0 : photoEmpty;

  return (
    <div className="search-quota">
      {fast && fast.searches_left > 0 && (
        <QuotaRow
          label="Fast photo searches"
          left={fast.searches_left}
          note={fast.enabled === false ? "Off · saved for demos" : "Used first"}
          title={
            fast.enabled === false
              ? "SearchApi.io credits (about 5-9 s per photo search) are kept for demos. Photo search uses the regular searches below."
              : "SearchApi.io credits: photo searches in about 5-9 s. When they run out, photo search uses the regular searches below."
          }
        />
      )}
      <QuotaRow
        label={text ? "Photo searches" : "Searches"}
        left={usage.searches_left}
        total={usage.searches_per_month}
        note={renewal && `Renews ${renewal}`}
        title="Searches left on this month's SerpApi plan"
      />
      {text && (
        <QuotaRow
          label="Text searches"
          left={text.searches_left}
          note="One-time credits"
          title="Serper.dev credits: text searches, and prices for photo results"
        />
      )}
      {(photoEmpty || textEmpty) && (
        <p className="search-quota-note">
          {photoEmpty && textEmpty
            ? "Searches are used up. Searches you've already run still load from the cache."
            : photoEmpty
              ? "Photo searches are used up this month; text search still works."
              : "Text search credits are used up; text search now uses photo searches."}
        </p>
      )}
    </div>
  );
}
