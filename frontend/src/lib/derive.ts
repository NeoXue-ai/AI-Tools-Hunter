/**
 * The semantic layer: turns persisted facts into the vocabulary the console
 * draws with. Kept pure and free of React so the rules stay readable and
 * testable in isolation.
 */

import type { Candidate, EvidenceStatus, PriorityFacts } from "../types";
import { parseTime } from "./format";

/** The pipeline only admits domains registered within 90 days (S2). */
export const FRESHNESS_WINDOW_DAYS = 90;
/** Tier 1: registered within 30 days. */
export const TIER1_DAYS = 30;
/** "Genuinely new" for scanning purposes. */
export const FRESH_DAYS = 7;

export type FreshnessKind = "fresh" | "tier1" | "tier2" | "stale" | "unknown";

export interface Freshness {
  kind: FreshnessKind;
  /** Registration age in whole days, or null when RDAP gave nothing back. */
  days: number | null;
  /** Position on the 0–90 day scale, 0–1. Null when unknown. */
  ratio: number | null;
}

/**
 * Registration age is the product's central fact, so it gets its own model
 * rather than being reduced to a number the eye has to compare.
 */
export function freshnessOf(candidate: Candidate): Freshness {
  const days = candidate.newness.rdap_age_days;
  if (days === null || days === undefined || !Number.isFinite(days)) {
    return { kind: "unknown", days: null, ratio: null };
  }
  const ratio = Math.min(1, Math.max(0, days / FRESHNESS_WINDOW_DAYS));
  if (days <= FRESH_DAYS) return { kind: "fresh", days, ratio };
  if (days <= TIER1_DAYS) return { kind: "tier1", days, ratio };
  if (days <= FRESHNESS_WINDOW_DAYS) return { kind: "tier2", days, ratio };
  return { kind: "stale", days, ratio: 1 };
}

/** Tailwind text/border/background triple per freshness kind. */
export const FRESHNESS_CLASS: Record<FreshnessKind, string> = {
  fresh: "text-fresh border-fresh/40 bg-fresh/10",
  tier1: "text-accent border-accent/40 bg-accent-soft",
  tier2: "text-warm border-warm/40 bg-warm/10",
  stale: "text-dead border-dead/40 bg-dead/10",
  unknown: "text-ink-3 border-line-strong bg-sunken",
};

/** Raw hex-ish CSS var name for SVG strokes, where Tailwind classes can't reach. */
export const FRESHNESS_VAR: Record<FreshnessKind, string> = {
  fresh: "--dh-fresh",
  tier1: "--dh-accent",
  tier2: "--dh-warm",
  stale: "--dh-dead",
  unknown: "--dh-slatey",
};

export interface PrioritySegment {
  key: keyof Omit<PriorityFacts, "score" | "formula_version">;
  weight: number;
  contribution: number;
}

/** Fixed weights from `review-priority-v1`; the bar must not invent its own. */
const WEIGHTS: Record<PrioritySegment["key"], number> = {
  product_evidence_contribution: 0.35,
  early_presence_contribution: 0.3,
  low_exposure_contribution: 0.2,
  data_completeness_contribution: 0.15,
};

const SEGMENT_ORDER: PrioritySegment["key"][] = [
  "product_evidence_contribution",
  "early_presence_contribution",
  "low_exposure_contribution",
  "data_completeness_contribution",
];

/** Decomposes the score so the rail can explain it instead of asserting it. */
export function prioritySegments(priority: PriorityFacts | null): PrioritySegment[] {
  if (!priority) return [];
  return SEGMENT_ORDER.map((key) => ({
    key,
    weight: WEIGHTS[key],
    contribution: priority[key] ?? 0,
  }));
}

/** One hue per contribution, warm-to-cool by weight so the eye reads rank. */
export const SEGMENT_COLOR: Record<PrioritySegment["key"], string> = {
  product_evidence_contribution: "--dh-accent",
  early_presence_contribution: "--dh-fresh",
  low_exposure_contribution: "--dh-warm",
  data_completeness_contribution: "--dh-slatey",
};

export const SEGMENT_CLASS: Record<PrioritySegment["key"], string> = {
  product_evidence_contribution: "bg-accent",
  early_presence_contribution: "bg-fresh",
  low_exposure_contribution: "bg-warm",
  data_completeness_contribution: "bg-slatey",
};

// ── Filtering ───────────────────────────────────────────────────────────────

export type FilterKey = "all" | "fresh" | "tier1" | "reachable" | "unverified";
export type SortKey = "priority" | "age" | "seen";

export function matchesFilter(candidate: Candidate, filter: FilterKey): boolean {
  const days = candidate.newness.rdap_age_days;
  switch (filter) {
    case "all":
      return true;
    case "fresh":
      return days !== null && days <= FRESH_DAYS;
    case "tier1":
      return days !== null && days <= TIER1_DAYS;
    case "reachable":
      return candidate.reachability.status === "passed";
    case "unverified":
      return (
        candidate.newness.status === "unknown" ||
        candidate.reachability.status === "unknown"
      );
  }
}

export function sortCandidates(items: Candidate[], sort: SortKey): Candidate[] {
  const copy = [...items];
  switch (sort) {
    case "priority":
      // The server already orders by priority; keep that order as the default.
      return copy;
    case "age":
      // Youngest first — unknown ages sink to the bottom rather than sorting as 0.
      return copy.sort((a, b) => {
        const left = a.newness.rdap_age_days;
        const right = b.newness.rdap_age_days;
        if (left === null && right === null) return 0;
        if (left === null) return 1;
        if (right === null) return -1;
        return left - right;
      });
    case "seen":
      return copy.sort((a, b) => {
        const left = parseTime(a.newness.ct_first_seen_at) ?? 0;
        const right = parseTime(b.newness.ct_first_seen_at) ?? 0;
        return right - left;
      });
  }
}

/** How many candidates each filter would keep — drives the chip counters. */
export function filterCounts(items: Candidate[]): Record<FilterKey, number> {
  return {
    all: items.length,
    fresh: items.filter((c) => matchesFilter(c, "fresh")).length,
    tier1: items.filter((c) => matchesFilter(c, "tier1")).length,
    reachable: items.filter((c) => matchesFilter(c, "reachable")).length,
    unverified: items.filter((c) => matchesFilter(c, "unverified")).length,
  };
}

// ── Status helpers ──────────────────────────────────────────────────────────

export const STATUS_TEXT_CLASS: Record<EvidenceStatus, string> = {
  passed: "text-fresh",
  failed: "text-dead",
  unknown: "text-ink-3",
};

export const STATUS_DOT_CLASS: Record<EvidenceStatus, string> = {
  passed: "bg-fresh",
  failed: "bg-dead",
  unknown: "bg-slatey",
};

/** Human sentence for the reachability gate, e.g. "HTTP 200 · same root". */
export function reachabilityLine(candidate: Candidate, dict: {
  httpStatus: string;
  httpUnverified: string;
  rootMatches: string;
  rootDiffers: string;
}): { status: EvidenceStatus; text: string } {
  const facts = candidate.reachability;
  if (facts.status === "unknown") {
    return { status: "unknown", text: dict.httpUnverified };
  }
  const code = facts.http_status_code;
  const parts: string[] = [];
  parts.push(code ? dict.httpStatus.replace("{code}", String(code)) : dict.httpUnverified);
  if (facts.same_root === true) parts.push(dict.rootMatches);
  else if (facts.same_root === false) parts.push(dict.rootDiffers);
  return { status: facts.status, text: parts.join(" · ") };
}

/** The safest URL to open: canonical first, then final, then the bare domain. */
export function outboundUrl(candidate: Candidate): string {
  return (
    candidate.canonical_url ??
    candidate.reachability.final_url ??
    `https://${candidate.domain}`
  );
}
