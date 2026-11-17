export const STATUS_COLOR: Record<string, string> = {
  HEALTHY: "#3fd49a", DEGRADED: "#f4b740", FAILED: "#ff6b66", BLOCKED: "#ff8c42", RECOVERING: "#5bb8f5",
};
export const IMPACT_COLOR: Record<string, string> = {
  SOURCE: "#ff6b66", DIRECT: "#ff8c42", INDIRECT: "#f4b740", UNAFFECTED: "#5e7c85",
};
export const SEVERITY_COLOR: Record<string, string> = {
  LOW: "#3fd49a", MODERATE: "#f4b740", HIGH: "#ff8c42", CRITICAL: "#ff6b66",
};
export const TYPE_LABEL: Record<string, string> = {
  FRONTEND: "Frontend Service", BACKEND: "Backend Service", API_GATEWAY: "API Gateway", AUTH: "Authentication Service",
  DATABASE: "Database", CACHE: "Cache", MESSAGE_QUEUE: "Message Queue", EXTERNAL_API: "External API",
  STORAGE: "Storage Service", CUSTOM: "Custom Service",
};
export const FAILURE_LABEL: Record<string, string> = {
  COMPLETE_SERVICE_FAILURE: "Complete Service Failure", DATABASE_FAILURE: "Database Failure",
  NETWORK_FAILURE: "Network Failure", API_TIMEOUT: "API Timeout", HIGH_LATENCY: "High Latency",
  RESOURCE_EXHAUSTION: "Resource Exhaustion", PARTIAL_DEGRADATION: "Partial Service Degradation",
  MULTIPLE_SIMULTANEOUS: "Multiple Simultaneous Failures",
};

/** "FAILURE_PROPAGATED" -> "Failure propagated" (sentence case for event names). */
export const sentence = (s?: string | null) => {
  const t = (s || "").toLowerCase().replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const title = (s?: string | null) =>
  (s || "").toLowerCase().split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");

export function fmtDate(iso?: string | null, withTime = true) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, withTime
    ? { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric" });
}

export function ago(iso?: string | null) {
  if (!iso) return "–";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const minutes = (m?: number | null) => (m === null || m === undefined ? "–" : `${Math.round(m * 10) / 10} min`);
export const pct = (v?: number | null, digits = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`);

export function scoreColor(score?: number | null) {
  if (score === null || score === undefined) return "#5e7c85";
  if (score >= 85) return "#3fd49a";
  if (score >= 70) return "#9bd86a";
  if (score >= 55) return "#f4b740";
  if (score >= 40) return "#ff8c42";
  return "#ff6b66";
}

export const ACTIVE_SIM = ["RUNNING", "PAUSED", "PROPAGATED", "STOPPED", "RECOVERING", "PARTIALLY_RECOVERED"];

// Categorical series colours for charts comparing non-status things (e.g. recovery strategies).
// Kept clear of the status hues: lens violet, sky, sand, rose.
export const SERIES = ["#a69bff", "#5bb8f5", "#e0c38c", "#e58fb8"];
