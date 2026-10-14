import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import { CandidateView } from "./components/CandidateView";
import { CommandPalette } from "./components/CommandPalette";
import { Header } from "./components/Header";
import { PipelineDrawer } from "./components/PipelineDrawer";
import { QueueView } from "./components/QueueView";
import { ToastProvider, useToast } from "./components/Toasts";
import {
  useActorId,
  useHotkeys,
  useLanguage,
  useNow,
  useRoute,
  useTheme,
} from "./hooks";
import { DICT } from "./i18n";
import type { FilterKey, SortKey } from "./lib/derive";
import type { Candidate, DiscoveryCounts, ReviewAction } from "./types";

export default function App() {
  return (
    <ToastProvider>
      <Console />
    </ToastProvider>
  );
}

function Console() {
  const { theme, toggle: toggleTheme } = useTheme();
  const { lang, toggle: toggleLang } = useLanguage();
  const { actorId, setActorId } = useActorId();
  const { route, push } = useRoute();
  const dict = DICT[lang];
  const now = useNow();
  const toast = useToast();

  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [counts, setCounts] = useState<DiscoveryCounts | null>(null);

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("priority");

  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [pipelineToken, setPipelineToken] = useState(0);

  const searchRef = useRef<HTMLInputElement>(null);

  const loadQueue = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") setLoading(true);
    setRefreshing(true);
    try {
      setCandidates(await api.queue());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadCounts = useCallback(async () => {
    try {
      const overview = await api.overview();
      setCounts(overview.counts);
    } catch {
      /* the header summary is decorative; a failure must not blank the queue */
    }
  }, []);

  useEffect(() => {
    void loadQueue("initial");
    void loadCounts();
  }, [loadCounts, loadQueue]);

  const scan = useCallback(async () => {
    setScanning(true);
    try {
      const summary = await api.runDiscovery(20);
      const created = summary.candidates_created;
      toast.push({
        tone: created > 0 ? "success" : "info",
        message:
          lang === "zh"
            ? `扫描完成：${summary.certificates_seen} 张证书，新增 ${created} 个候选`
            : `Scan done: ${summary.certificates_seen} certificates, ${created} new candidates`,
      });
      await Promise.all([loadQueue(), loadCounts()]);
      setPipelineToken((token) => token + 1);
    } catch (caught) {
      toast.push({
        tone: "danger",
        message: caught instanceof Error ? caught.message : String(caught),
      });
    } finally {
      setScanning(false);
    }
  }, [lang, loadCounts, loadQueue, toast]);

  // The next candidate to offer after a decision, wrapping around the queue.
  const nextCandidateId = useMemo(() => {
    const currentId = route.candidateId;
    if (!currentId) return null;
    const index = candidates.findIndex((item) => item.candidate_id === currentId);
    const rest =
      index === -1
        ? candidates
        : [...candidates.slice(index + 1), ...candidates.slice(0, index)];
    return rest[0]?.candidate_id ?? null;
  }, [candidates, route.candidateId]);

  const handleDecided = useCallback(
    async (_action: ReviewAction, _domain: string, nextId: string | null) => {
      await loadQueue();
      void loadCounts();
      push(nextId ? { name: "candidate", candidateId: nextId } : { name: "queue" });
    },
    [loadCounts, loadQueue, push],
  );

  const openCandidate = useCallback(
    (candidateId: string) => push({ name: "candidate", candidateId }),
    [push],
  );

  useHotkeys({
    "mod+k": (event) => {
      event.preventDefault();
      setPaletteOpen((open) => !open);
    },
    "/": (event) => {
      if (route.name !== "queue") return;
      event.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    },
  });

  const onQueue = route.name === "queue";

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-[80] focus:rounded-md focus:bg-surface focus:px-3 focus:py-1.5 focus:text-xs focus:text-ink focus:shadow-pop"
      >
        {dict.skipToContent}
      </a>

      <Header
        dict={dict}
        counts={counts}
        queueLength={candidates.length}
        theme={theme}
        lang={lang}
        actorId={actorId}
        scanning={scanning}
        refreshing={refreshing}
        onToggleTheme={toggleTheme}
        onToggleLang={toggleLang}
        onOpenPipeline={() => setPipelineOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
        onScan={scan}
        onRefresh={() => void loadQueue()}
        onSetActor={setActorId}
      />

      <main id="main">
        {onQueue ? (
          <QueueView
            dict={dict}
            candidates={candidates}
            loading={loading}
            error={error}
            now={now}
            query={query}
            filter={filter}
            sort={sort}
            onQueryChange={setQuery}
            onFilterChange={setFilter}
            onSortChange={setSort}
            onOpen={openCandidate}
            onRetry={() => void loadQueue()}
            onScan={scan}
            scanning={scanning}
            searchInputRef={searchRef}
          />
        ) : route.candidateId ? (
          <CandidateView
            dict={dict}
            candidateId={route.candidateId}
            actorId={actorId}
            now={now}
            onBack={() => push({ name: "queue" })}
            onDecided={handleDecided}
            nextCandidateId={nextCandidateId}
            onOpenCandidate={openCandidate}
          />
        ) : null}
      </main>

      {onQueue && (
        <footer className="mx-auto max-w-[1400px] px-4 pb-8 sm:px-6">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-4 text-2xs text-ink-3">
            <span className="label">{dict.keyboardHint}</span>
            <Hint keys={["J", "K"]} text={dict.hintMove} />
            <Hint keys={["↵"]} text={dict.hintOpen} />
            <Hint keys={["/"]} text={dict.hintSearch} />
            <Hint keys={["⌘", "K"]} text={dict.commands} />
          </div>
        </footer>
      )}

      <PipelineDrawer
        dict={dict}
        lang={lang}
        open={pipelineOpen}
        onClose={() => setPipelineOpen(false)}
        scanning={scanning}
        onScan={scan}
        refreshToken={pipelineToken}
      />

      <CommandPalette
        dict={dict}
        theme={theme}
        open={paletteOpen}
        candidates={candidates}
        onClose={() => setPaletteOpen(false)}
        onOpenCandidate={openCandidate}
        onToggleTheme={toggleTheme}
        onToggleLang={toggleLang}
        onRefresh={() => void loadQueue()}
        onScan={scan}
        onOpenPipeline={() => setPipelineOpen(true)}
      />
    </div>
  );
}

const Hint: React.FC<{ keys: string[]; text: string }> = ({ keys, text }) => (
  <span className="flex items-center gap-1.5">
    <span className="flex gap-0.5">
      {keys.map((key) => (
        <kbd key={key} className="kbd">
          {key}
        </kbd>
      ))}
    </span>
    {text}
  </span>
);
