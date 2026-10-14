import React from "react";

import type { Dict } from "../i18n";
import { fill } from "../i18n";
import {
  FRESHNESS_VAR,
  TIER1_DAYS,
  type Freshness,
  type PrioritySegment,
  SEGMENT_CLASS,
  SEGMENT_COLOR,
  STATUS_DOT_CLASS,
  type FilterKey,
  type SortKey,
} from "../lib/derive";
import type { EvidenceStatus } from "../types";

/* ─────────────────────────────── Freshness meter ─────────────────────────── */

/**
 * The signature element: registration age plotted on the pipeline's own 0–90
 * day admission window. "2 days" and "78 days" are the same visual grammar, so
 * the queue can be scanned without reading a single number.
 *
 * Built from `<span>`s because the inline variant lives inside the queue's row
 * button, where only phrasing content is legal.
 */
export const FreshnessMeter: React.FC<{
  freshness: Freshness;
  dict: Dict;
  variant?: "inline" | "full";
}> = ({ freshness, dict, variant = "inline" }) => {
  const color = `rgb(var(${FRESHNESS_VAR[freshness.kind]}))`;
  const tier1Ratio = TIER1_DAYS / 90;

  const label =
    freshness.days === null ? dict.ageUnknown : fill(dict.ageDays, { n: freshness.days });

  if (variant === "full") {
    return (
      <span className="flex flex-col gap-2.5">
        <span className="flex items-baseline justify-between">
          <span className="label">{dict.freshness}</span>
          <span className="font-mono text-xs font-medium" style={{ color }}>
            {label}
          </span>
        </span>

        <span className="block">
          <span className="relative block h-2 rounded-full bg-sunken">
            <span className="absolute inset-y-0 left-0 block w-full overflow-hidden rounded-full">
              {freshness.ratio !== null && (
                <span
                  className="block h-full rounded-full transition-[width] duration-500 ease-out"
                  style={{
                    width: `${Math.max(freshness.ratio * 100, 1.5)}%`,
                    background: `linear-gradient(90deg, ${color}66, ${color})`,
                  }}
                />
              )}
            </span>
            {/* Tier-1 boundary: the point where a domain stops being "very new". */}
            <span
              className="absolute -top-1 bottom-[-4px] block w-px bg-line-strong"
              style={{ left: `${tier1Ratio * 100}%` }}
            />
            {freshness.ratio !== null && (
              <span
                className="absolute top-1/2 block h-3.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface transition-[left] duration-500 ease-out"
                style={{ left: `${freshness.ratio * 100}%`, background: color }}
              />
            )}
          </span>

          <span className="relative mt-1.5 block h-4">
            <span className="absolute left-0 font-mono text-[10px] text-ink-3">0</span>
            <span
              className="absolute -translate-x-1/2 font-mono text-[10px] text-ink-3"
              style={{ left: `${tier1Ratio * 100}%` }}
            >
              {dict.tier1Tick}
            </span>
            <span className="absolute right-0 font-mono text-[10px] text-ink-3">
              {dict.tier2Tick}
            </span>
          </span>
        </span>

        <span className="flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink-3">
          <span>
            {dict.ctFirstSeen}
            {" · "}
            <span className="font-mono text-ink-2">
              {freshness.days === null ? "—" : `${freshness.days}d`}
            </span>
          </span>
          <span>{dict.scaleNote}</span>
        </span>
      </span>
    );
  }

  // Inline: a ruler, not a progress bar. A 2-day-old domain must still read as
  // "barely into the window", so the track keeps visible contrast and the head
  // marker is clamped inside it rather than overhanging either end.
  const headPercent = freshness.ratio === null ? 0 : freshness.ratio * 100;
  const headClamped = Math.min(95, Math.max(5, headPercent));

  return (
    <span className="flex items-center gap-2">
      <span className="relative block h-2 w-[104px] shrink-0 rounded-full bg-line-strong/60">
        {freshness.ratio !== null && (
          <>
            <span
              className="absolute inset-y-0 left-0 block rounded-full"
              style={{
                width: `${Math.max(headPercent, 5)}%`,
                background: `linear-gradient(90deg, ${color}55, ${color})`,
              }}
            />
            <span
              className="absolute top-1/2 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface"
              style={{ left: `${headClamped}%`, background: color }}
            />
          </>
        )}
        <span
          className="absolute -inset-y-1 block w-px bg-ink-3/35"
          style={{ left: `${tier1Ratio * 100}%` }}
        />
      </span>
      <span
        className="truncate font-mono text-xs font-medium"
        style={{ color: freshness.ratio === null ? undefined : color }}
      >
        {freshness.days === null ? (
          <span className="text-ink-3" title={dict.ageUnknown}>
            —
          </span>
        ) : (
          `${freshness.days}d`
        )}
      </span>
    </span>
  );
};

/* ─────────────────────────────── Priority meter ──────────────────────────── */

/** The 4-segment decomposition bar: why the score is what it is. */
export const PriorityBar: React.FC<{ segments: PrioritySegment[]; className?: string }> = ({
  segments,
  className = "",
}) => {
  const total = segments.reduce((sum, segment) => sum + segment.contribution, 0);
  return (
    <span
      className={`flex h-1.5 overflow-hidden rounded-full bg-sunken ${className}`}
      aria-hidden="true"
    >
      {total > 0 &&
        segments.map((segment) => (
          <span
            key={segment.key}
            className={`block h-full ${SEGMENT_CLASS[segment.key]}`}
            style={{ width: `${(segment.contribution / total) * 100}%` }}
          />
        ))}
    </span>
  );
};

export const PriorityLegend: React.FC<{ segments: PrioritySegment[]; dict: Dict }> = ({
  segments,
  dict,
}) => {
  const labelOf: Record<PrioritySegment["key"], string> = {
    product_evidence_contribution: dict.weightProduct,
    early_presence_contribution: dict.weightEarly,
    low_exposure_contribution: dict.weightLowExposure,
    data_completeness_contribution: dict.weightCompleteness,
  };

  return (
    <ul className="space-y-2">
      {segments.map((segment) => (
        <li key={segment.key} className="flex items-center gap-2.5 text-xs">
          <span
            className="h-2 w-2 shrink-0 rounded-[2px]"
            style={{ background: `rgb(var(${SEGMENT_COLOR[segment.key]}))` }}
          />
          <span className="min-w-0 flex-1 truncate text-ink-2">{labelOf[segment.key]}</span>
          <span className="font-mono text-ink-3">×{segment.weight.toFixed(2)}</span>
          <span className="w-10 text-right font-mono font-medium text-ink">
            {segment.contribution.toFixed(2)}
          </span>
        </li>
      ))}
    </ul>
  );
};

/* ─────────────────────────────── Small pieces ────────────────────────────── */

export const StatusDot: React.FC<{ status: EvidenceStatus; pulse?: boolean }> = ({
  status,
  pulse,
}) => (
  <span className="relative inline-flex h-1.5 w-1.5 shrink-0">
    {pulse && (
      <span
        className={`absolute inset-0 animate-pulse-ring rounded-full ${STATUS_DOT_CLASS[status]}`}
      />
    )}
    <span className={`relative h-1.5 w-1.5 rounded-full ${STATUS_DOT_CLASS[status]}`} />
  </span>
);

export const Pill: React.FC<{
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "fresh" | "warm" | "dead";
  mono?: boolean;
  className?: string;
}> = ({ children, tone = "neutral", mono, className = "" }) => {
  const tones = {
    neutral: "border-line-strong bg-sunken text-ink-2",
    accent: "border-accent/30 bg-accent-soft text-accent",
    fresh: "border-fresh/30 bg-fresh/10 text-fresh",
    warm: "border-warm/30 bg-warm/10 text-warm",
    dead: "border-dead/30 bg-dead/10 text-dead",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium ${
        mono ? "font-mono" : ""
      } ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
};

export const Skeleton: React.FC<{ className?: string }> = ({ className = "" }) => (
  <div className={`shimmer rounded-md ${className}`} />
);

export const FilterChip: React.FC<{
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}> = ({ active, onClick, label, count }) => (
  <button
    type="button"
    onClick={onClick}
    aria-pressed={active}
    className={`btn btn-sm rounded-full border ${
      active
        ? "border-ink bg-ink text-canvas"
        : "border-line text-ink-2 hover:border-line-strong hover:text-ink"
    }`}
  >
    {label}
    <span className={`font-mono ${active ? "text-canvas/70" : "text-ink-3"}`}>{count}</span>
  </button>
);

export const FILTER_ORDER: FilterKey[] = ["all", "fresh", "tier1", "reachable", "unverified"];
export const SORT_ORDER: SortKey[] = ["priority", "age", "seen"];
