import React, { useEffect, useState } from "react";
import { Activity, Radar, RefreshCw, ScrollText, X } from "lucide-react";

import { api } from "../api";
import type { Dict, Language } from "../i18n";
import { useDismissable } from "../hooks";
import { formatCount } from "../lib/format";
import type { DiscoveryOverview } from "../types";
import { Skeleton, StatusDot } from "./primitives";

/** Probe outcome codes are a fixed dev-facing enum, kept next to their use. */
const OUTCOME_LABELS: Record<string, { zh: string; en: string }> = {
  success: { zh: "成功", en: "Success" },
  dns_not_found: { zh: "DNS 未解析", en: "DNS not found" },
  dns_timeout: { zh: "DNS 超时", en: "DNS timeout" },
  tls_error: { zh: "TLS 错误", en: "TLS error" },
  connect_timeout: { zh: "连接超时", en: "Connect timeout" },
  http_4xx: { zh: "HTTP 4xx", en: "HTTP 4xx" },
  http_429: { zh: "HTTP 429", en: "HTTP 429" },
  http_5xx: { zh: "HTTP 5xx", en: "HTTP 5xx" },
  redirect_loop: { zh: "重定向循环", en: "Redirect loop" },
  robots_disallowed: { zh: "robots 禁止", en: "Robots disallowed" },
  render_timeout: { zh: "渲染超时", en: "Render timeout" },
  content_insufficient: { zh: "内容不足", en: "Content insufficient" },
  blocked_ssrf: { zh: "SSRF 拦截", en: "Blocked (SSRF)" },
};

export const PipelineDrawer: React.FC<{
  dict: Dict;
  lang: Language;
  open: boolean;
  onClose: () => void;
  scanning: boolean;
  onScan: () => void;
  refreshToken: number;
}> = ({ dict, lang, open, onClose, scanning, onScan, refreshToken }) => {
  const [overview, setOverview] = useState<DiscoveryOverview | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logMissing, setLogMissing] = useState(false);
  const [loading, setLoading] = useState(true);

  useDismissable(open, onClose);

  // Counts refresh on open and whenever a scan finishes; the log polls, since
  // it is the one thing that changes while the drawer just sits there.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    api
      .overview()
      .then((data) => {
        if (alive) setOverview(data);
      })
      .catch(() => {
        if (alive) setOverview(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, refreshToken]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const pull = async () => {
      try {
        const body = await api.log(200);
        if (!alive) return;
        setLogMissing(!body.exists);
        setLogLines(body.lines);
      } catch {
        if (alive) setLogMissing(true);
      }
    };
    void pull();
    const timer = window.setInterval(pull, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [open]);

  if (!open) return null;

  const counts = overview?.counts;
  const metrics: { label: string; value: number | undefined }[] = [
    { label: dict.countQueue, value: counts?.review_queue },
    { label: dict.countCandidates, value: counts?.candidates },
    { label: dict.countDomains, value: counts?.domains },
    { label: dict.countSourceEvents, value: counts?.source_events },
    { label: dict.countObservations, value: counts?.observations },
    { label: dict.countVersions, value: counts?.candidate_versions },
  ];

  const recent = [...(overview?.domains ?? [])]
    .filter((snapshot) => snapshot.first_seen_at || snapshot.observed_at)
    .sort((a, b) => {
      const left = Date.parse(a.first_seen_at ?? a.observed_at ?? "") || 0;
      const right = Date.parse(b.first_seen_at ?? b.observed_at ?? "") || 0;
      return right - left;
    })
    .slice(0, 40);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-ink/20 backdrop-blur-[2px] animate-fade-in dark:bg-black/50"
        onClick={onClose}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={dict.pipelineTitle}
        className="relative flex h-full w-full max-w-[26rem] flex-col border-l border-line bg-canvas shadow-pop animate-slide-in-right"
      >
        <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-line px-4">
          <Activity className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold text-ink">{dict.pipelineTitle}</h2>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onScan}
            disabled={scanning}
            className="btn btn-sm btn-outline"
          >
            <Radar className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
            {scanning ? dict.scanning : dict.scan}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={dict.hintClose}
            className="btn btn-sm btn-quiet px-1.5"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {/* Counts */}
          <section className="border-b border-line px-4 py-4">
            {loading && !counts ? (
              <div className="grid grid-cols-3 gap-2">
                {[0, 1, 2, 3, 4, 5].map((index) => (
                  <Skeleton key={index} className="h-14" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {metrics.map((metric) => (
                  <div
                    key={metric.label}
                    className="rounded-md border border-line bg-surface px-2.5 py-2"
                  >
                    <div className="label truncate">{metric.label}</div>
                    <div className="mt-1 font-mono text-lg font-semibold leading-none text-ink">
                      {formatCount(metric.value)}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-3 flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-2">
              <span className="label shrink-0">{dict.cursor}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-2xs text-ink-2">
                {overview?.cursor ?? dict.cursorNone}
              </span>
            </div>
          </section>

          {/* Recent domains */}
          <section className="border-b border-line">
            <div className="flex items-center gap-2 px-4 py-2.5">
              <h3 className="label">{dict.recentDomains}</h3>
              <span className="ml-auto font-mono text-2xs text-ink-3">{recent.length}</span>
            </div>
            {recent.length === 0 ? (
              <p className="px-4 pb-4 text-xs text-ink-3">{dict.runtimeLogEmpty}</p>
            ) : (
              <ul className="max-h-72 overflow-y-auto px-2 pb-3">
                {recent.map((snapshot) => {
                  const code = snapshot.outcome_code ?? "";
                  const label = OUTCOME_LABELS[code];
                  const ok = code === "success";
                  return (
                    <li
                      key={snapshot.domain}
                      className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-sunken"
                    >
                      <StatusDot status={ok ? "passed" : "failed"} />
                      <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-2">
                        {snapshot.domain}
                      </span>
                      <span className="shrink-0 font-mono text-2xs text-ink-3">
                        {snapshot.status_code ?? (label ? (lang === "zh" ? label.zh : label.en) : "—")}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Runtime log */}
          <section>
            <div className="flex items-center gap-2 px-4 py-2.5">
              <ScrollText className="h-3.5 w-3.5 text-ink-3" />
              <h3 className="label">{dict.runtimeLog}</h3>
              <span className="ml-auto flex items-center gap-1.5 text-2xs text-ink-3">
                <RefreshCw className="h-3 w-3" />
                {dict.autoRefresh}
              </span>
            </div>
            <pre className="max-h-80 overflow-auto border-t border-line bg-sunken px-4 py-3 font-mono text-[10.5px] leading-relaxed text-ink-2">
              {logMissing || logLines.length === 0
                ? dict.runtimeLogEmpty
                : logLines.join("\n")}
            </pre>
          </section>
        </div>
      </aside>
    </div>
  );
};
