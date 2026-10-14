import React, { useEffect, useRef, useState } from "react";
import {
  Check,
  Command,
  Languages,
  Moon,
  Radar,
  RefreshCw,
  Sun,
  UserRound,
} from "lucide-react";

import type { Dict, Language, Theme } from "../i18n";
import { formatCount } from "../lib/format";
import type { DiscoveryCounts } from "../types";

/** A small signal mark: arcs radiating from a source, like a CT log sweep. */
export const SignalMark: React.FC<{ className?: string }> = ({ className = "h-4 w-4" }) => (
  <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
    <circle cx="6" cy="18" r="2.1" fill="currentColor" />
    <path
      d="M6 12.2a5.8 5.8 0 0 1 5.8 5.8"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      opacity="0.85"
    />
    <path
      d="M6 6.2A11.8 11.8 0 0 1 17.8 18"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      opacity="0.55"
    />
    <path
      d="M6 0.6A17.4 17.4 0 0 1 23.4 18"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      opacity="0.28"
    />
  </svg>
);

const HeaderButton: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }
> = ({ label, children, className = "", ...rest }) => (
  <button
    type="button"
    aria-label={label}
    title={label}
    className={`btn h-8 rounded-md px-2 text-ink-2 hover:bg-sunken hover:text-ink ${className}`}
    {...rest}
  >
    {children}
  </button>
);

export const Header: React.FC<{
  dict: Dict;
  counts: DiscoveryCounts | null;
  queueLength: number;
  theme: Theme;
  lang: Language;
  actorId: string;
  scanning: boolean;
  refreshing: boolean;
  onToggleTheme: () => void;
  onToggleLang: () => void;
  onOpenPipeline: () => void;
  onOpenPalette: () => void;
  onScan: () => void;
  onRefresh: () => void;
  onSetActor: (value: string) => void;
}> = ({
  dict,
  counts,
  queueLength,
  theme,
  lang,
  actorId,
  scanning,
  refreshing,
  onToggleTheme,
  onToggleLang,
  onOpenPipeline,
  onOpenPalette,
  onScan,
  onRefresh,
  onSetActor,
}) => (
  <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur-md">
    <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
      <a
        href="/"
        className="flex shrink-0 items-center gap-2.5 rounded-md py-1 pr-1 text-ink"
        aria-label={dict.product}
      >
        <SignalMark className="h-[18px] w-[18px] text-accent" />
        <span className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight">{dict.product}</span>
          <span className="hidden text-2xs text-ink-3 sm:inline">{dict.tagline}</span>
        </span>
      </a>

      <div className="ml-1 hidden items-center gap-1.5 border-l border-line pl-3 md:flex">
        <button
          type="button"
          onClick={onOpenPipeline}
          className="btn btn-sm gap-2 rounded-md text-ink-2 hover:bg-sunken hover:text-ink"
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inset-0 animate-pulse-ring rounded-full bg-fresh" />
            <span className="relative h-1.5 w-1.5 rounded-full bg-fresh" />
          </span>
          <span>{dict.pipeline}</span>
          {counts && (
            <span className="font-mono text-ink-3">
              {formatCount(counts.domains)}
            </span>
          )}
        </button>
        <span className="rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-2xs text-ink-2">
          {queueLength} {dict.countQueue}
        </span>
      </div>

      <div className="flex-1" />

      <button
        type="button"
        onClick={onOpenPalette}
        className="hidden h-8 items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-xs text-ink-3 transition-colors hover:border-line-strong hover:text-ink-2 sm:flex"
      >
        <Command className="h-3.5 w-3.5" />
        <span className="w-20 truncate text-left">{dict.searchShort}</span>
        <kbd className="kbd">⌘K</kbd>
      </button>

      <button
        type="button"
        onClick={onScan}
        disabled={scanning}
        className="btn btn-sm btn-primary"
      >
        <Radar className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
        <span className="hidden sm:inline">{scanning ? dict.scanning : dict.scan}</span>
      </button>

      <HeaderButton label={dict.refresh} onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
      </HeaderButton>

      <HeaderButton
        label={dict.theme}
        onClick={onToggleTheme}
        className="hidden sm:inline-flex"
      >
        {theme === "dark" ? (
          <Sun className="h-3.5 w-3.5" />
        ) : (
          <Moon className="h-3.5 w-3.5" />
        )}
      </HeaderButton>

      <HeaderButton
        label={dict.language}
        onClick={onToggleLang}
        className="hidden sm:inline-flex"
      >
        <Languages className="h-3.5 w-3.5" />
        <span className="ml-1 font-mono text-2xs uppercase">{lang}</span>
      </HeaderButton>

      <OperatorChip dict={dict} actorId={actorId} onSetActor={onSetActor} />
    </div>
  </header>
);

/**
 * Reviewer identity is required for every mutation, but it must not interrupt
 * triage — so it lives as a chip that only opens when it needs attention.
 */
const OperatorChip: React.FC<{
  dict: Dict;
  actorId: string;
  onSetActor: (value: string) => void;
}> = ({ dict, actorId, onSetActor }) => {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(actorId);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const next = draft.trim();
    if (!next) return;
    onSetActor(next);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => {
          setDraft(actorId);
          setOpen((prev) => !prev);
        }}
        className={`btn h-8 gap-1.5 rounded-md px-2 ${
          actorId
            ? "text-ink-2 hover:bg-sunken hover:text-ink"
            : "border border-warm/40 bg-warm/10 text-warm hover:bg-warm/20"
        }`}
        title={actorId ? `${dict.operator}: ${actorId}` : dict.operatorSet}
      >
        <UserRound className="h-3.5 w-3.5" />
        <span className="max-w-[7rem] truncate font-mono text-2xs">
          {actorId || dict.operatorUnset}
        </span>
      </button>

      {open && (
        <form
          onSubmit={submit}
          className="absolute right-0 top-10 z-50 w-72 rounded-card border border-line bg-raised p-3.5 shadow-pop animate-rise-in"
        >
          <div className="label mb-1.5">{dict.operatorSet}</div>
          <p className="mb-2.5 text-xs leading-relaxed text-ink-2">{dict.operatorHint}</p>
          <div className="flex gap-2">
            <input
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={dict.operatorPlaceholder}
              className="h-8 min-w-0 flex-1 rounded-md border border-line bg-sunken px-2.5 font-mono text-xs text-ink outline-none placeholder:text-ink-3 focus:border-accent"
            />
            <button type="submit" className="btn btn-sm btn-primary" disabled={!draft.trim()}>
              <Check className="h-3.5 w-3.5" />
            </button>
          </div>
        </form>
      )}
    </div>
  );
};
