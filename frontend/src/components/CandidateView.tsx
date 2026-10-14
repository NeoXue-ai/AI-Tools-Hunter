import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Link2,
  Quote,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";

import { api } from "../api";
import type { Dict } from "../i18n";
import { fill } from "../i18n";
import {
  absoluteTime,
  displayDomain,
  formatScore,
  relativeTime,
} from "../lib/format";
import {
  freshnessOf,
  outboundUrl,
  prioritySegments,
  reachabilityLine,
} from "../lib/derive";
import type { CandidateContext, ReasonTag, ReviewAction } from "../types";
import { useToast } from "./Toasts";
import {
  FreshnessMeter,
  Pill,
  PriorityBar,
  PriorityLegend,
  Skeleton,
  StatusDot,
} from "./primitives";

const ALL_REASON_TAGS: ReasonTag[] = [
  "blog",
  "prompt_directory",
  "open_source_demo",
  "agency",
  "broken_site",
  "insufficient_evidence",
];

const ACTION_ORDER: ReviewAction[] = ["approve", "defer", "reject", "blocklist"];

interface CandidateViewProps {
  dict: Dict;
  candidateId: string;
  actorId: string;
  now: number;
  onBack: () => void;
  onDecided: (action: ReviewAction, domain: string, nextId: string | null) => void;
  nextCandidateId: string | null;
  onOpenCandidate: (candidateId: string) => void;
}

export const CandidateView: React.FC<CandidateViewProps> = ({
  dict,
  candidateId,
  actorId,
  now,
  onBack,
  onDecided,
  nextCandidateId,
  onOpenCandidate,
}) => {
  const [candidate, setCandidate] = useState<CandidateContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<ReviewAction | null>(null);
  const [confirming, setConfirming] = useState<"reject" | "blocklist" | null>(null);
  const [reasonTags, setReasonTags] = useState<ReasonTag[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [copied, setCopied] = useState(false);

  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCandidate(await api.candidate(candidateId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    setReasonTags([]);
    setConfirming(null);
    setLeaving(false);
    load();
  }, [load]);

  const decide = useCallback(
    async (action: ReviewAction) => {
      if (!candidate) return;
      if (!actorId) {
        toast.push({
          tone: "danger",
          message: dict.operatorRequired,
        });
        return;
      }
      setSubmitting(action);
      try {
        await api.decide(candidate.candidate_id, candidate.version, action, actorId, reasonTags);
        setLeaving(true);
        const doneLabels: Record<ReviewAction, string> = {
          approve: dict.approveDone,
          defer: dict.deferDone,
          reject: dict.rejectDone,
          blocklist: dict.blocklistDone,
        };
        toast.push({
          tone: action === "approve" ? "success" : "info",
          message: `${doneLabels[action]} · ${displayDomain(candidate.domain)}`,
        });
        window.setTimeout(() => onDecided(action, candidate.domain, nextCandidateId), 220);
      } catch (caught) {
        setSubmitting(null);
        toast.push({
          tone: "danger",
          message: caught instanceof Error ? caught.message : String(caught),
        });
        load();
      }
    },
    [actorId, candidate, dict, load, nextCandidateId, onDecided, reasonTags, toast],
  );

  // The decision is the only mutation, so it owns the letter keys.
  useEffect(() => {
    if (!candidate || submitting) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (confirming) return;
      const map: Record<string, ReviewAction> = {
        a: "approve",
        d: "defer",
        r: "reject",
        b: "blocklist",
      };
      const action = map[event.key.toLowerCase()];
      if (!action) return;
      event.preventDefault();
      if (action === "reject" || action === "blocklist") setConfirming(action);
      else void decide(action);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [candidate, confirming, decide, submitting]);

  if (loading) return <DetailSkeleton />;

  if (error || !candidate) {
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <ShieldAlert className="mx-auto h-7 w-7 text-ink-3" />
        <h1 className="mt-4 text-sm font-semibold text-ink">
          {error ? dict.errorTitle : dict.notFound}
        </h1>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-2">
          {error ?? dict.notFoundHint}
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <button type="button" onClick={onBack} className="btn btn-sm btn-outline">
            <ArrowLeft className="h-3.5 w-3.5" />
            {dict.backToQueue}
          </button>
          <button type="button" onClick={load} className="btn btn-sm btn-primary">
            {dict.retry}
          </button>
        </div>
      </div>
    );
  }

  const freshness = freshnessOf(candidate);
  const segments = prioritySegments(candidate.priority);
  const reach = reachabilityLine(candidate, dict);

  const copyDomain = async () => {
    try {
      await navigator.clipboard.writeText(candidate.domain);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard is optional */
    }
  };

  return (
    <div
      className={`mx-auto max-w-[1400px] px-4 py-6 transition-all duration-200 sm:px-6 sm:py-8 ${
        leaving ? "pointer-events-none translate-y-1 opacity-0" : "opacity-100"
      }`}
    >
      <button
        type="button"
        onClick={onBack}
        className="btn btn-sm btn-quiet -ml-1.5 mb-4 text-ink-2"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {dict.backToQueue}
      </button>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        {/* ── Case file ─────────────────────────────────────────────────── */}
        <div className="space-y-5 lg:col-span-8">
          <section className="plane p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="font-mono text-xl font-semibold tracking-tight text-ink sm:text-2xl">
                    {displayDomain(candidate.domain)}
                  </h1>
                  <Pill tone="accent">{dict.outcomes[candidate.primary_outcome]}</Pill>
                  <Pill mono>{dict.version.replace("{n}", String(candidate.version))}</Pill>
                  <Pill mono>{dict.authorLabels[candidate.author_kind]}</Pill>
                </div>

                {candidate.name_suggestion && (
                  <p className="mt-2 text-sm font-medium text-ink">
                    {candidate.name_suggestion}
                  </p>
                )}
                <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-2">
                  {candidate.description_suggestion || dict.noDescription}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                <button type="button" onClick={copyDomain} className="btn btn-sm btn-outline">
                  {copied ? (
                    <Check className="h-3.5 w-3.5 text-fresh" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                  <span className="hidden sm:inline">{copied ? dict.copied : dict.copyDomain}</span>
                </button>
                <a
                  href={outboundUrl(candidate)}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="btn btn-sm btn-primary"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {dict.visitSite}
                </a>
              </div>
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-x-5 gap-y-3 border-t border-line pt-4 sm:grid-cols-4">
              <MetaCell
                label={dict.ctFirstSeen}
                value={relativeTime(candidate.newness.ct_first_seen_at, now, dict, fill)}
                title={absoluteTime(candidate.newness.ct_first_seen_at)}
              />
              <MetaCell
                label={dict.rdapRegistered}
                value={relativeTime(candidate.newness.rdap_registration_at, now, dict, fill)}
                title={absoluteTime(candidate.newness.rdap_registration_at)}
              />
              <MetaCell
                label={dict.reachability}
                value={reach.text}
                tone={reach.status === "passed" ? "fresh" : reach.status === "failed" ? "dead" : undefined}
              />
              <MetaCell
                label={dict.checkedAt.replace(" {t}", "")}
                value={absoluteTime(candidate.newness.checked_at)}
              />
            </dl>
          </section>

          {/* Evidence chain */}
          <section className="plane overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
              <div>
                <h2 className="text-sm font-semibold text-ink">{dict.evidenceChain}</h2>
                <p className="mt-0.5 text-xs text-ink-3">{dict.evidenceChainHint}</p>
              </div>
              <span className="shrink-0 font-mono text-xs text-ink-3">
                {fill(dict.evidenceCount, { n: candidate.evidence.length })}
              </span>
            </div>

            {candidate.evidence.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <Quote className="mx-auto h-5 w-5 text-ink-3" />
                <p className="mt-3 text-sm font-medium text-ink">{dict.noEvidence}</p>
                <p className="mt-1 text-xs text-ink-2">{dict.noEvidenceHint}</p>
              </div>
            ) : (
              <ol className="relative px-5 py-2">
                {candidate.evidence.map((item, index) => (
                  <li key={`${item.type}-${index}`} className="relative flex gap-4 py-4">
                    {/* Timeline rail: a dot per quote, connected between items. */}
                    <div className="relative flex w-4 shrink-0 justify-center">
                      {index < candidate.evidence.length - 1 && (
                        <span className="absolute top-4 bottom-[-1rem] w-px bg-line" />
                      )}
                      <span className="relative mt-1 h-2 w-2 rounded-full border-2 border-accent bg-surface" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="label">{dict.evidenceTypes[item.type]}</span>
                        <span className="font-mono text-2xs text-ink-3">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                      </div>

                      <blockquote className="mt-2 rounded-md border-l-2 border-accent bg-sunken px-3.5 py-2.5">
                        <p className="text-[13px] leading-relaxed text-ink">{item.quote}</p>
                      </blockquote>

                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="mt-1.5 inline-flex max-w-full items-center gap-1.5 font-mono text-2xs text-ink-3 transition-colors hover:text-accent"
                        >
                          <Link2 className="h-3 w-3 shrink-0" />
                          <span className="truncate">{item.url}</span>
                        </a>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* Internal links discovered during the probe */}
          {candidate.internal_links.length > 0 && (
            <section className="plane p-5">
              <h2 className="text-sm font-semibold text-ink">{dict.internalLinks}</h2>
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {candidate.internal_links.slice(0, 24).map((link) => (
                  <li key={link}>
                    <a
                      href={link}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex max-w-[18rem] items-center gap-1 rounded-full border border-line px-2.5 py-1 font-mono text-2xs text-ink-2 transition-colors hover:border-line-strong hover:text-accent"
                    >
                      <span className="truncate">{link.replace(/^https?:\/\//, "")}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <DecisionHistory
            dict={dict}
            candidate={candidate}
            actorId={actorId}
            onRevoked={load}
          />

          {/* Raw payload */}
          <section className="plane overflow-hidden">
            <button
              type="button"
              onClick={() => setShowRaw((prev) => !prev)}
              aria-expanded={showRaw}
              className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left transition-colors hover:bg-sunken"
            >
              <span>
                <span className="block text-sm font-semibold text-ink">{dict.technical}</span>
                <span className="mt-0.5 block text-xs text-ink-3">{dict.technicalHint}</span>
              </span>
              <ChevronDown
                className={`h-4 w-4 shrink-0 text-ink-3 transition-transform duration-200 ${
                  showRaw ? "rotate-180" : ""
                }`}
              />
            </button>
            {showRaw && (
              <pre className="max-h-96 overflow-auto border-t border-line bg-sunken px-5 py-4 font-mono text-2xs leading-relaxed text-ink-2">
                {JSON.stringify(candidate, null, 2)}
              </pre>
            )}
          </section>
        </div>

        {/* ── Decision rail ─────────────────────────────────────────────── */}
        <aside className="space-y-5 lg:sticky lg:top-20 lg:col-span-4 lg:max-h-[calc(100vh-5.5rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
          <section className="plane p-5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-ink">{dict.decision}</h2>
              <span className="font-mono text-2xs text-ink-3">
                {candidate.version && dict.version.replace("{n}", String(candidate.version))}
              </span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">{dict.decisionHint}</p>

            {!actorId && (
              <p className="mt-3 flex items-start gap-2 rounded-md border border-warm/40 bg-warm/10 px-2.5 py-2 text-xs leading-relaxed text-warm">
                <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                {dict.operatorRequired}
              </p>
            )}

            <div className="mt-4 space-y-2">
              <DecisionButton
                dict={dict}
                action="approve"
                submitting={submitting}
                onClick={() => void decide("approve")}
              />
              <DecisionButton
                dict={dict}
                action="defer"
                submitting={submitting}
                onClick={() => void decide("defer")}
              />
              <div className="grid grid-cols-2 gap-2">
                <DecisionButton
                  dict={dict}
                  action="reject"
                  submitting={submitting}
                  onClick={() => setConfirming("reject")}
                />
                <DecisionButton
                  dict={dict}
                  action="blocklist"
                  submitting={submitting}
                  onClick={() => setConfirming("blocklist")}
                />
              </div>
            </div>

            <div className="mt-4 border-t border-line pt-3.5">
              <div className="label mb-2">{dict.reasonTags}</div>
              <div className="flex flex-wrap gap-1.5">
                {ALL_REASON_TAGS.map((tag) => {
                  const active = reasonTags.includes(tag);
                  return (
                    <button
                      key={tag}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setReasonTags((prev) =>
                          active ? prev.filter((item) => item !== tag) : [...prev, tag],
                        )
                      }
                      className={`btn h-6 rounded-full border px-2.5 text-2xs ${
                        active
                          ? "border-accent bg-accent-soft text-accent"
                          : "border-line text-ink-3 hover:border-line-strong hover:text-ink-2"
                      }`}
                    >
                      {dict.reasonLabels[tag]}
                    </button>
                  );
                })}
              </div>
            </div>

            {nextCandidateId && (
              <button
                type="button"
                onClick={() => onOpenCandidate(nextCandidateId)}
                className="mt-4 flex w-full items-center justify-between rounded-md border border-line px-3 py-2 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
              >
                <span>{dict.openNext}</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )}
          </section>

          {/* Signals */}
          <section className="plane p-5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold text-ink">{dict.priority}</h2>
              {candidate.priority && (
                <span className="font-mono text-2xs text-ink-3">
                  {dict.formula.replace("{v}", candidate.priority.formula_version.replace("review-priority-", ""))}
                </span>
              )}
            </div>

            {candidate.priority ? (
              <>
                <div className="mt-3 flex items-end gap-3">
                  <span className="font-mono text-3xl font-semibold leading-none tracking-tight text-ink">
                    {formatScore(candidate.priority.score)}
                  </span>
                  <span className="pb-0.5 text-xs text-ink-3">/ 1.00</span>
                </div>
                <PriorityBar segments={segments} className="mt-3 h-2" />
                <div className="mt-4 border-t border-line pt-3.5">
                  <PriorityLegend segments={segments} dict={dict} />
                </div>
              </>
            ) : (
              <p className="mt-3 text-xs text-ink-3">{dict.noPriority}</p>
            )}

            <div className="mt-5 border-t border-line pt-4">
              <FreshnessMeter freshness={freshness} dict={dict} variant="full" />
            </div>
          </section>

          {/* Reachability */}
          <section className="plane p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink">{dict.reachability}</h2>
              <span className="flex items-center gap-1.5">
                <StatusDot status={reach.status} pulse={reach.status === "passed"} />
                <span className="font-mono text-2xs text-ink-3">
                  {dict.statusLabels[reach.status]}
                </span>
              </span>
            </div>
            <dl className="mt-3 space-y-2 text-xs">
              <FactRow label={dict.colReachability} value={reach.text} />
              <FactRow
                label={dict.finalUrl}
                value={
                  candidate.reachability.final_url ? (
                    <a
                      href={candidate.reachability.final_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="break-all font-mono text-accent hover:underline"
                    >
                      {candidate.reachability.final_url}
                    </a>
                  ) : (
                    "—"
                  )
                }
              />
              <FactRow
                label={dict.sameRoot}
                value={
                  candidate.reachability.same_root === null
                    ? "—"
                    : candidate.reachability.same_root
                      ? dict.rootMatches
                      : dict.rootDiffers
                }
              />
            </dl>
          </section>
        </aside>
      </div>

      {/* Mobile action bar */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-canvas/95 px-3 py-2.5 backdrop-blur-md lg:hidden">
        <div className="mx-auto flex max-w-2xl gap-2">
          {ACTION_ORDER.map((action) => (
            <button
              key={action}
              type="button"
              disabled={submitting !== null}
              onClick={() =>
                action === "reject" || action === "blocklist"
                  ? setConfirming(action)
                  : void decide(action)
              }
              className={`btn btn-sm flex-1 ${ACTION_STYLES[action]}`}
            >
              {submitting === action ? dict.submitting : dict.actionLabels[action]}
            </button>
          ))}
        </div>
      </div>
      <div className="h-16 lg:hidden" />

      {confirming && (
        <ConfirmDialog
          dict={dict}
          action={confirming}
          busy={submitting !== null}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const action = confirming;
            setConfirming(null);
            void decide(action);
          }}
        />
      )}
    </div>
  );
};

/* ─────────────────────────────── Pieces ──────────────────────────────────── */

const MetaCell: React.FC<{
  label: string;
  value: string;
  title?: string;
  tone?: "fresh" | "dead";
}> = ({ label, value, title, tone }) => (
  <div className="min-w-0">
    <dt className="label">{label}</dt>
    <dd
      title={title}
      className={`mt-1 truncate font-mono text-xs ${
        tone === "fresh" ? "text-fresh" : tone === "dead" ? "text-dead" : "text-ink"
      }`}
    >
      {value}
    </dd>
  </div>
);

const FactRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex gap-3">
    <dt className="w-20 shrink-0 text-ink-3">{label}</dt>
    <dd className="min-w-0 flex-1 text-ink-2">{value}</dd>
  </div>
);

const ACTION_STYLES: Record<ReviewAction, string> = {
  approve: "btn-primary",
  defer: "btn-outline",
  reject: "btn-danger",
  blocklist: "btn-danger",
};

const DecisionButton: React.FC<{
  dict: Dict;
  action: ReviewAction;
  submitting: ReviewAction | null;
  onClick: () => void;
}> = ({ dict, action, submitting, onClick }) => {
  const hints: Record<ReviewAction, string> = {
    approve: dict.approveHint,
    defer: dict.deferHint,
    reject: dict.rejectHint,
    blocklist: dict.blocklistHint,
  };
  const keys: Record<ReviewAction, string> = {
    approve: "A",
    defer: "D",
    reject: "R",
    blocklist: "B",
  };
  const primary = action === "approve";

  return (
    <button
      type="button"
      disabled={submitting !== null}
      onClick={onClick}
      title={hints[action]}
      className={`btn btn-md w-full justify-between ${
        primary ? "btn-primary" : action === "defer" ? "btn-outline" : "btn-danger"
      }`}
    >
      <span className="truncate">{dict.actionLabels[action]}</span>
      <span className="flex shrink-0 items-center gap-1.5">
        {submitting === action && (
          <span className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
        )}
        <kbd
          className={`kbd border-0 bg-transparent px-0 ${
            primary ? "text-accent-ink/70" : "text-ink-3"
          }`}
        >
          {keys[action]}
        </kbd>
      </span>
    </button>
  );
};

const DecisionHistory: React.FC<{
  dict: Dict;
  candidate: CandidateContext;
  actorId: string;
  onRevoked: () => void;
}> = ({ dict, candidate, actorId, onRevoked }) => {
  const toast = useToast();
  const decisions = candidate.audit?.decisions ?? [];
  const [revoking, setRevoking] = useState<string | null>(null);

  const revoke = async (decisionId: string) => {
    if (!actorId) {
      toast.push({ tone: "danger", message: dict.operatorRequired });
      return;
    }
    setRevoking(decisionId);
    try {
      await api.revoke(candidate.candidate_id, candidate.version, decisionId, actorId, "revoked from console");
      toast.push({ tone: "info", message: dict.revoke });
      onRevoked();
    } catch (caught) {
      toast.push({
        tone: "danger",
        message: caught instanceof Error ? caught.message : String(caught),
      });
    } finally {
      setRevoking(null);
    }
  };

  return (
    <section className="plane overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <h2 className="text-sm font-semibold text-ink">{dict.history}</h2>
        <span className="font-mono text-xs text-ink-3">{decisions.length}</span>
      </div>

      {decisions.length === 0 ? (
        <p className="px-5 py-6 text-center text-xs text-ink-3">{dict.historyEmpty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {decisions.map((decision) => (
            <li key={decision.decision_id} className="flex items-center gap-3 px-5 py-3">
              <Pill
                tone={
                  decision.action === "approve"
                    ? "fresh"
                    : decision.action === "defer"
                      ? "warm"
                      : "dead"
                }
                className={decision.revoked ? "opacity-45 line-through" : ""}
              >
                {dict.actionLabels[decision.action]}
              </Pill>

              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-ink">
                  {fill(dict.decidedBy, { actor: decision.actor_id })}
                </div>
                <div
                  className="mt-0.5 font-mono text-2xs text-ink-3"
                  title={absoluteTime(decision.decided_at)}
                >
                  {absoluteTime(decision.decided_at)}
                  {decision.reason_tags.length > 0 && (
                    <span> · {decision.reason_tags.map((tag) => dict.reasonLabels[tag]).join(" / ")}</span>
                  )}
                </div>
              </div>

              {decision.revoked ? (
                <span className="shrink-0 text-2xs text-ink-3">{dict.revoked}</span>
              ) : (
                <button
                  type="button"
                  disabled={revoking !== null}
                  onClick={() => void revoke(decision.decision_id)}
                  className="btn btn-sm btn-quiet shrink-0 text-ink-3"
                >
                  <RotateCcw
                    className={`h-3 w-3 ${revoking === decision.decision_id ? "animate-spin" : ""}`}
                  />
                  {dict.revoke}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

const ConfirmDialog: React.FC<{
  dict: Dict;
  action: "reject" | "blocklist";
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}> = ({ dict, action, busy, onCancel, onConfirm }) => {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/25 p-4 backdrop-blur-[2px] animate-fade-in dark:bg-black/55"
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-card border border-line bg-raised p-5 shadow-pop animate-rise-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-dead/10 text-dead">
            <ShieldAlert className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink">
              {action === "reject" ? dict.confirmRejectTitle : dict.confirmBlocklistTitle}
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-2">
              {action === "reject" ? dict.confirmRejectBody : dict.confirmBlocklistBody}
            </p>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn btn-sm btn-quiet">
            {dict.cancel}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="btn btn-sm bg-dead text-white hover:brightness-110"
          >
            {dict.confirm}
          </button>
        </div>
      </div>
    </div>
  );
};

const DetailSkeleton: React.FC = () => (
  <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
    <Skeleton className="h-7 w-28" />
    <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-12">
      <div className="space-y-5 lg:col-span-8">
        <Skeleton className="h-44" />
        <Skeleton className="h-72" />
      </div>
      <div className="space-y-5 lg:col-span-4">
        <Skeleton className="h-56" />
        <Skeleton className="h-64" />
      </div>
    </div>
  </div>
);
