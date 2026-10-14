import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Command,
  Languages,
  Moon,
  Radar,
  RefreshCw,
  Search,
  Sun,
  Activity,
  CornerDownLeft,
} from "lucide-react";

import type { Dict, Theme } from "../i18n";
import { displayDomain } from "../lib/format";
import { freshnessOf } from "../lib/derive";
import type { Candidate } from "../types";

export interface PaletteAction {
  id: string;
  label: string;
  icon: React.ReactNode;
  run: () => void;
}

export const CommandPalette: React.FC<{
  dict: Dict;
  theme: Theme;
  open: boolean;
  candidates: Candidate[];
  onClose: () => void;
  onOpenCandidate: (candidateId: string) => void;
  onToggleTheme: () => void;
  onToggleLang: () => void;
  onRefresh: () => void;
  onScan: () => void;
  onOpenPipeline: () => void;
}> = ({
  dict,
  theme,
  open,
  candidates,
  onClose,
  onOpenCandidate,
  onToggleTheme,
  onToggleLang,
  onRefresh,
  onScan,
  onOpenPipeline,
}) => {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
    }
  }, [open]);

  const actions: PaletteAction[] = useMemo(
    () => [
      {
        id: "scan",
        label: dict.cmdScan,
        icon: <Radar className="h-3.5 w-3.5" />,
        run: onScan,
      },
      {
        id: "refresh",
        label: dict.cmdRefresh,
        icon: <RefreshCw className="h-3.5 w-3.5" />,
        run: onRefresh,
      },
      {
        id: "pipeline",
        label: dict.cmdPipeline,
        icon: <Activity className="h-3.5 w-3.5" />,
        run: onOpenPipeline,
      },
      {
        id: "theme",
        label: dict.cmdTheme,
        icon:
          theme === "dark" ? (
            <Sun className="h-3.5 w-3.5" />
          ) : (
            <Moon className="h-3.5 w-3.5" />
          ),
        run: onToggleTheme,
      },
      {
        id: "lang",
        label: dict.cmdLang,
        icon: <Languages className="h-3.5 w-3.5" />,
        run: onToggleLang,
      },
    ],
    [
      dict.cmdLang,
      dict.cmdPipeline,
      dict.cmdRefresh,
      dict.cmdScan,
      dict.cmdTheme,
      onOpenPipeline,
      onRefresh,
      onScan,
      onToggleLang,
      onToggleTheme,
      theme,
    ],
  );

  const needle = query.trim().toLowerCase();

  const matchedCandidates = useMemo(() => {
    if (!needle) return candidates.slice(0, 6);
    return candidates
      .filter(
        (candidate) =>
          candidate.domain.toLowerCase().includes(needle) ||
          candidate.name_suggestion?.toLowerCase().includes(needle) ||
          candidate.description_suggestion?.toLowerCase().includes(needle),
      )
      .slice(0, 8);
  }, [candidates, needle]);

  const matchedActions = useMemo(
    () => (needle ? actions.filter((action) => action.label.toLowerCase().includes(needle)) : actions),
    [actions, needle],
  );

  /** One flat index space so arrow keys walk candidates then actions. */
  const flatCount = matchedCandidates.length + matchedActions.length;

  useEffect(() => {
    setCursor((prev) => Math.min(prev, Math.max(0, flatCount - 1)));
  }, [flatCount]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((prev) => (flatCount === 0 ? 0 : (prev + 1) % flatCount));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((prev) => (flatCount === 0 ? 0 : (prev - 1 + flatCount) % flatCount));
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        if (cursor < matchedCandidates.length) {
          const candidate = matchedCandidates[cursor];
          if (candidate) {
            onOpenCandidate(candidate.candidate_id);
            onClose();
          }
        } else {
          const action = matchedActions[cursor - matchedCandidates.length];
          if (action) {
            action.run();
            onClose();
          }
        }
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [cursor, flatCount, matchedActions, matchedCandidates, onClose, onOpenCandidate, open]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[65] flex items-start justify-center bg-ink/25 p-4 pt-[12vh] backdrop-blur-[2px] animate-fade-in dark:bg-black/55"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-card border border-line bg-raised shadow-pop animate-rise-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-line px-3.5">
          <Search className="h-4 w-4 shrink-0 text-ink-3" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={dict.palettePlaceholder}
            className="h-12 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          />
          <kbd className="kbd shrink-0">ESC</kbd>
        </div>

        <div ref={listRef} className="max-h-[22rem] overflow-y-auto p-1.5">
          {flatCount === 0 && (
            <p className="px-3 py-8 text-center text-xs text-ink-3">{dict.paletteNoResults}</p>
          )}

          {matchedCandidates.length > 0 && (
            <>
              <div className="label px-2.5 py-1.5">{dict.paletteCandidates}</div>
              {matchedCandidates.map((candidate, index) => {
                const freshness = freshnessOf(candidate);
                return (
                  <button
                    key={candidate.candidate_id}
                    type="button"
                    data-index={index}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => {
                      onOpenCandidate(candidate.candidate_id);
                      onClose();
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left ${
                      cursor === index ? "bg-sunken" : ""
                    }`}
                  >
                    <Command className="h-3.5 w-3.5 shrink-0 text-ink-3" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-xs font-medium text-ink">
                        {displayDomain(candidate.domain)}
                      </span>
                      {(candidate.name_suggestion || candidate.description_suggestion) && (
                        <span className="block truncate text-2xs text-ink-3">
                          {candidate.name_suggestion ?? candidate.description_suggestion}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 font-mono text-2xs text-ink-3">
                      {freshness.days === null ? "—" : `${freshness.days}d`}
                    </span>
                  </button>
                );
              })}
            </>
          )}

          {matchedActions.length > 0 && (
            <>
              <div className="label px-2.5 pb-1.5 pt-3">{dict.paletteActions}</div>
              {matchedActions.map((action, index) => {
                const flat = matchedCandidates.length + index;
                return (
                  <button
                    key={action.id}
                    type="button"
                    data-index={flat}
                    onMouseEnter={() => setCursor(flat)}
                    onClick={() => {
                      action.run();
                      onClose();
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-xs ${
                      cursor === flat ? "bg-sunken text-ink" : "text-ink-2"
                    }`}
                  >
                    <span className="shrink-0 text-ink-3">{action.icon}</span>
                    <span className="min-w-0 flex-1 truncate">{action.label}</span>
                  </button>
                );
              })}
            </>
          )}
        </div>

        <div className="flex items-center gap-3 border-t border-line px-3.5 py-2 text-2xs text-ink-3">
          <span className="flex items-center gap-1">
            <kbd className="kbd">↑</kbd>
            <kbd className="kbd">↓</kbd>
            {dict.hintMove}
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd">
              <CornerDownLeft className="h-2.5 w-2.5" />
            </kbd>
            {dict.hintOpen}
          </span>
        </div>
      </div>
    </div>
  );
};
