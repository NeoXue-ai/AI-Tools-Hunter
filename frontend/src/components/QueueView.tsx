import React, { useEffect, useMemo, useState } from "react";
import { ArrowRight, ChevronDown, Radar, Search, X } from "lucide-react";

import { isTypingTarget } from "../hooks";
import type { Dict } from "../i18n";
import { fill } from "../i18n";
import { displayDomain, formatScore, relativeTime } from "../lib/format";
import {
  filterCounts,
  freshnessOf,
  matchesFilter,
  prioritySegments,
  reachabilityLine,
  sortCandidates,
  type FilterKey,
  type SortKey,
} from "../lib/derive";
import type { Candidate } from "../types";
import {
  FILTER_ORDER,
  FilterChip,
  FreshnessMeter,
  Pill,
  PriorityBar,
  Skeleton,
  SORT_ORDER,
  StatusDot,
} from "./primitives";

interface QueueViewProps {
  dict: Dict;
  candidates: Candidate[];
  loading: boolean;
  error: string | null;
  now: number;
  query: string;
  filter: FilterKey;
  sort: SortKey;
  onQueryChange: (value: string) => void;
  onFilterChange: (value: FilterKey) => void;
  onSortChange: (value: SortKey) => void;
  onOpen: (candidateId: string) => void;
  onRetry: () => void;
  onScan: () => void;
  scanning: boolean;
  searchInputRef?: React.RefObject<HTMLInputElement | null>;
}

export const QueueView: React.FC<QueueViewProps> = ({
  dict,
  candidates,
  loading,
  error,
  now,
  query,
  filter,
  sort,
  onQueryChange,
  onFilterChange,
  onSortChange,
  onOpen,
  onRetry,
  onScan,
  scanning,
  searchInputRef,
}) => {
  const [highlight, setHighlight] = useState(0);

  const counts = useMemo(() => filterCounts(candidates), [candidates]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matched = candidates.filter((candidate) => {
      if (!matchesFilter(candidate, filter)) return false;
      if (!needle) return true;
      return (
        candidate.domain.toLowerCase().includes(needle) ||
        candidate.name_suggestion?.toLowerCase().includes(needle) ||
        candidate.description_suggestion?.toLowerCase().includes(needle) ||
        candidate.evidence.some((item) => item.quote.toLowerCase().includes(needle))
      );
    });
    return sortCandidates(matched, sort);
  }, [candidates, filter, query, sort]);

  // A shorter list must not leave the highlight pointing past its end.
  useEffect(() => {
    setHighlight((prev) => Math.min(prev, Math.max(0, visible.length - 1)));
  }, [visible.length]);

  /**
   * j/k walk the queue and Enter opens — the whole triage loop without the
   * mouse. These stay local to the view so the detail page keeps a/d/r/b.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setHighlight((prev) => Math.min(prev + 1, Math.max(0, visible.length - 1)));
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setHighlight((prev) => Math.max(prev - 1, 0));
      } else if (event.key === "Enter" || event.key === "o") {
        const target = visible[highlight];
        if (target) {
          event.preventDefault();
          onOpen(target.candidate_id);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [highlight, onOpen, visible]);

  useEffect(() => {
    document
      .querySelector<HTMLElement>(`[data-queue-index="${highlight}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [highlight]);

  const filterLabels: Record<FilterKey, string> = {
    all: dict.filterAll,
    fresh: dict.filterFresh,
    tier1: dict.filterTier1,
    reachable: dict.filterReachable,
    unverified: dict.filterUnverified,
  };
  const sortLabels: Record<SortKey, string> = {
    priority: dict.sortPriority,
    age: dict.sortAge,
    seen: dict.sortSeen,
  };

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-7 sm:px-6 sm:py-9">
      {/* Page head */}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">{dict.queueTitle}</h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-2">{dict.queueSubtitle}</p>
        </div>
        {!loading && (
          <span className="font-mono text-xs text-ink-3">
            {fill(dict.showingCount, { shown: visible.length, total: candidates.length })}
          </span>
        )}
      </div>

      {/* Toolbar */}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[13rem] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" />
          <input
            ref={searchInputRef}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={dict.searchPlaceholder}
            aria-label={dict.searchPlaceholder}
            className="h-8 w-full rounded-md border border-line bg-surface pl-8 pr-7 text-xs text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent"
          />
          {query && (
            <button
              type="button"
              onClick={() => onQueryChange("")}
              aria-label={dict.clearFilters}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-3 hover:text-ink"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {FILTER_ORDER.map((key) => (
            <FilterChip
              key={key}
              active={filter === key}
              onClick={() => onFilterChange(key)}
              label={filterLabels[key]}
              count={counts[key]}
            />
          ))}
        </div>

        <div className="relative ml-auto">
          <select
            value={sort}
            onChange={(event) => onSortChange(event.target.value as SortKey)}
            aria-label={dict.sortBy}
            className="h-8 appearance-none rounded-md border border-line bg-surface pl-2.5 pr-7 text-xs text-ink-2 outline-none hover:border-line-strong focus:border-accent"
          >
            {SORT_ORDER.map((key) => (
              <option key={key} value={key}>
                {sortLabels[key]}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" />
        </div>
      </div>

      {error && (
        <div className="mt-5 flex items-center justify-between gap-4 rounded-card border border-dead/30 bg-dead/[0.06] px-4 py-3">
          <span className="text-sm text-dead">{error}</span>
          <button type="button" onClick={onRetry} className="btn btn-sm btn-outline">
            {dict.retry}
          </button>
        </div>
      )}

      {/* Column headers — the ledger's ruler */}
      {!loading && visible.length > 0 && (
        <div className="mt-6 hidden items-center gap-4 border-b border-line px-3 pb-2 lg:flex">
          <span className="label w-6 shrink-0">{dict.rank}</span>
          <span className="label flex-1">{dict.colTarget}</span>
          <span className="label w-[10.5rem] shrink-0">{dict.colNewness}</span>
          <span className="label w-[10rem] shrink-0">{dict.colReachability}</span>
          <span className="label w-[7.5rem] shrink-0 text-right">{dict.colPriority}</span>
          <span className="w-4 shrink-0" />
        </div>
      )}

      <div className="mt-2">
        {loading ? (
          <QueueSkeleton />
        ) : visible.length === 0 ? (
          <QueueEmpty
            dict={dict}
            filtered={candidates.length > 0}
            onClear={() => {
              onQueryChange("");
              onFilterChange("all");
            }}
            onScan={onScan}
            scanning={scanning}
          />
        ) : (
          <ul className="divide-y divide-line">
            {visible.map((candidate, index) => (
              <QueueRow
                key={candidate.candidate_id}
                dict={dict}
                candidate={candidate}
                rank={index + 1}
                now={now}
                onOpen={onOpen}
                highlighted={index === highlight}
                onHover={() => setHighlight(index)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

const QueueRow: React.FC<{
  dict: Dict;
  candidate: Candidate;
  rank: number;
  now: number;
  onOpen: (candidateId: string) => void;
  highlighted: boolean;
  onHover: () => void;
}> = ({ dict, candidate, rank, now, onOpen, highlighted, onHover }) => {
  const freshness = freshnessOf(candidate);
  const segments = prioritySegments(candidate.priority);
  const reach = reachabilityLine(candidate, dict);
  const isNew = freshness.days !== null && freshness.days <= 7;

  const outcomeTone =
    candidate.primary_outcome === "publishable_ai_saas" ? "accent" : "neutral";

  return (
    <li>
      <button
        type="button"
        data-queue-index={rank - 1}
        onMouseMove={onHover}
        onFocus={onHover}
        onClick={() => onOpen(candidate.candidate_id)}
        aria-current={highlighted ? "true" : undefined}
        className={`group relative grid w-full grid-cols-[1.5rem_minmax(0,1fr)_1.25rem] items-start gap-x-4 gap-y-2 rounded-md px-3 py-3.5 text-left transition-colors lg:grid-cols-[1.5rem_minmax(0,1fr)_10.5rem_10rem_7.5rem_1rem] lg:items-center lg:gap-y-0 ${
          highlighted ? "bg-sunken" : "hover:bg-sunken"
        }`}
      >
        {/* The rail marker makes the keyboard cursor unmistakable. */}
        <span
          aria-hidden="true"
          className={`absolute left-0 top-1/2 h-7 w-[2px] -translate-y-1/2 rounded-full bg-accent transition-opacity ${
            highlighted ? "opacity-100" : "opacity-0"
          }`}
        />
        <span className="pt-0.5 font-mono text-xs text-ink-3 lg:pt-0">
          {String(rank).padStart(2, "0")}
        </span>

        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-[15px] font-semibold tracking-tight text-ink transition-colors group-hover:text-accent">
              {displayDomain(candidate.domain)}
            </span>
            {isNew && <Pill tone="fresh">{dict.newBadge}</Pill>}
            <Pill tone={outcomeTone}>{dict.outcomes[candidate.primary_outcome]}</Pill>
            {candidate.author_kind === "llm" && (
              <Pill mono>{dict.authorLlm}</Pill>
            )}
          </span>

          <span className="mt-1 block truncate text-xs text-ink-2">
            {candidate.name_suggestion && (
              <span className="font-medium text-ink-2">{candidate.name_suggestion}</span>
            )}
            {candidate.name_suggestion && candidate.description_suggestion && (
              <span className="text-ink-3"> · </span>
            )}
            {candidate.description_suggestion && (
              <span className="text-ink-3">{candidate.description_suggestion}</span>
            )}
            {!candidate.name_suggestion && !candidate.description_suggestion && (
              <span className="text-ink-3">
                {relativeTime(
                  candidate.newness.ct_first_seen_at,
                  now,
                  dict,
                  fill,
                )}
                {" · "}
                {dict.version.replace("{n}", String(candidate.version))}
              </span>
            )}
          </span>

          {/* Mobile: the three facts collapse under the target line. */}
          <span className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 lg:hidden">
            <FreshnessMeter freshness={freshness} dict={dict} />
            <span className="flex items-center gap-1.5 text-xs text-ink-2">
              <StatusDot status={reach.status} />
              {reach.text}
            </span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-ink">
                {formatScore(candidate.priority?.score)}
              </span>
              <PriorityBar segments={segments} className="w-14" />
            </span>
          </span>
        </span>

        {/* Desktop: fixed ledger columns. */}
        <span className="hidden lg:block">
          <FreshnessMeter freshness={freshness} dict={dict} />
        </span>

        <span className="hidden min-w-0 items-center gap-1.5 text-xs text-ink-2 lg:flex">
          <StatusDot status={reach.status} />
          <span className="truncate">{reach.text}</span>
        </span>

        <span className="hidden flex-col items-end gap-1.5 lg:flex">
          <span className="font-mono text-sm font-semibold text-ink">
            {formatScore(candidate.priority?.score)}
          </span>
          <PriorityBar segments={segments} className="w-16" />
        </span>

        <ArrowRight className="hidden h-4 w-4 shrink-0 text-ink-3 transition-all group-hover:translate-x-0.5 group-hover:text-accent lg:block" />
        <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 justify-self-end text-ink-3 transition-all group-hover:translate-x-0.5 group-hover:text-accent lg:hidden" />
      </button>
    </li>
  );
};

const QueueSkeleton: React.FC = () => (
  <ul className="divide-y divide-line">
    {[0, 1, 2, 3, 4].map((index) => (
      <li key={index} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-4 px-3 py-4">
        <Skeleton className="h-4 w-5" />
        <div className="space-y-2">
          <Skeleton className="h-4 w-52" />
          <Skeleton className="h-3 w-72 max-w-full" />
        </div>
      </li>
    ))}
  </ul>
);

const QueueEmpty: React.FC<{
  dict: Dict;
  filtered: boolean;
  onClear: () => void;
  onScan: () => void;
  scanning: boolean;
}> = ({ dict, filtered, onClear, onScan, scanning }) => (
  <div className="mt-6 flex flex-col items-center rounded-card border border-dashed border-line-strong px-6 py-16 text-center animate-fade-in">
    <div className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface text-ink-3">
      {filtered ? <Search className="h-5 w-5" /> : <Radar className="h-5 w-5" />}
    </div>
    <h2 className="mt-4 text-sm font-semibold text-ink">
      {filtered ? dict.queueEmptySearch : dict.queueFinished}
    </h2>
    <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-ink-2">
      {filtered ? dict.queueEmptySearchHint : dict.queueFinishedHint}
    </p>
    <div className="mt-5">
      {filtered ? (
        <button type="button" onClick={onClear} className="btn btn-sm btn-outline">
          {dict.clearFilters}
        </button>
      ) : (
        <button
          type="button"
          onClick={onScan}
          disabled={scanning}
          className="btn btn-sm btn-primary"
        >
          <Radar className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
          {scanning ? dict.scanning : dict.scan}
        </button>
      )}
    </div>
  </div>
);
