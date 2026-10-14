/**
 * Wire types for the AI-Tools-Hunter review API.
 *
 * These mirror `ai_tools_hunter.api.dependencies.review_projection` exactly — no
 * flattening, no invented fields. Everything the console renders is a fact the
 * backend already persisted.
 */

export type ReviewState = "pending" | "approved" | "deferred" | "rejected" | "blocklisted";
export type EvidenceStatus = "passed" | "failed" | "unknown";
export type ReviewAction = "approve" | "defer" | "reject" | "blocklist";
export type ActorKind = "rule" | "llm" | "human";

/** S1–S5 outcome vocabulary (`ai_tools_hunter.domain.candidates.CandidateOutcome`). */
export type CandidateOutcome =
  | "publishable_ai_saas"
  | "valid_but_not_ready"
  | "not_target"
  | "duplicate_or_existing"
  | "policy_excluded";

/** Where a quoted piece of evidence was lifted from. */
export type EvidenceType =
  | "source_event"
  | "title"
  | "meta_description"
  | "visible_text"
  | "h1"
  | "cta"
  | "pricing"
  | "exposure_check";

export type ReasonTag =
  | "blog"
  | "prompt_directory"
  | "open_source_demo"
  | "agency"
  | "broken_site"
  | "insufficient_evidence";

/** CT first-seen plus RDAP registration age — the "is it actually new?" gate. */
export interface NewnessFacts {
  status: EvidenceStatus;
  checked_at: string | null;
  ct_first_seen_at: string | null;
  rdap_tier: "tier1" | "tier2" | "unknown" | null;
  rdap_age_days: number | null;
  rdap_registration_at: string | null;
}

/** Bounded HTTP probe result — the "does it actually exist?" gate. */
export interface ReachabilityFacts {
  status: EvidenceStatus;
  http_status_code: number | null;
  final_url: string | null;
  canonical_url: string | null;
  same_root: boolean | null;
}

/**
 * The saved ordering score, decomposed. The weights are fixed at
 * 0.35 / 0.30 / 0.20 / 0.15, so the console can show *why* a candidate ranks
 * where it does instead of just printing a number.
 */
export interface PriorityFacts {
  score: number;
  formula_version: string;
  product_evidence_contribution: number;
  early_presence_contribution: number;
  low_exposure_contribution: number;
  data_completeness_contribution: number;
}

/** One quote the candidate's interpretation rests on. */
export interface CandidateEvidence {
  type: EvidenceType;
  quote: string;
  url: string | null;
}

export interface Candidate {
  candidate_id: string;
  domain: string;
  version: number;
  author_kind: ActorKind;
  primary_outcome: CandidateOutcome;
  classification_confidence: number;
  name_suggestion: string | null;
  description_suggestion: string | null;
  evidence: CandidateEvidence[];
  canonical_url: string | null;
  internal_links: string[];
  priority: PriorityFacts | null;
  review_state: ReviewState;
  newness: NewnessFacts;
  reachability: ReachabilityFacts;
}

export interface DecisionRecord {
  decision_id: string;
  action: ReviewAction;
  actor_id: string;
  decided_at: string;
  reason_tags: ReasonTag[];
  revoked: boolean;
}

export interface CandidateContext extends Candidate {
  audit?: { decisions: DecisionRecord[] };
}

export interface DiscoveryCounts {
  source_events: number;
  domains: number;
  observations: number;
  candidates: number;
  candidate_versions: number;
  review_queue: number;
}

export interface DomainSnapshot {
  domain: string;
  first_seen_at: string | null;
  observed_at: string | null;
  outcome_code: string | null;
  attempt_number: number | null;
  status_code: number | null;
  final_url: string | null;
  detail: string | null;
}

export interface DiscoveryOverview {
  cursor: string | null;
  domains: DomainSnapshot[];
  counts: DiscoveryCounts;
}

export interface DiscoveryRunSummary {
  status: "completed" | "queued" | "no_candidates";
  next_cursor: string | null;
  certificates_seen: number;
  events_added: number;
  roots_observed: number;
  strict_rejections: number;
  probes_run: number;
  candidates_created: number;
  source_errors: string[];
  pending_work: number;
}

/** A decision the console has committed, kept locally so the queue can react. */
export interface LocalDecision {
  action: ReviewAction;
  decidedAt: number;
  candidateId: string;
  domain: string;
}
