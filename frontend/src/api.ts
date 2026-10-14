/**
 * Thin, typed client for the loopback review API.
 *
 * Deliberately dumb: it maps the wire payload onto the types in `./types` and
 * surfaces server `detail` strings as thrown errors. All interpretation lives in
 * the components so the console never disagrees with the persisted facts.
 */

import type {
  Candidate,
  CandidateContext,
  DiscoveryOverview,
  DiscoveryRunSummary,
  ReasonTag,
  ReviewAction,
} from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { cache: "no-store", ...init });
  } catch (cause) {
    throw new ApiError("无法连接本地服务 / API unreachable", 0);
  }

  if (response.status === 204) return undefined as T;

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(detailOf(body, response.status), response.status);
  }
  return body as T;
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // The 409 concurrent-decision payload nests its own `detail`.
    if (detail && typeof detail === "object" && "detail" in detail) {
      const nested = (detail as { detail: unknown }).detail;
      if (typeof nested === "string") return nested;
    }
  }
  return `HTTP ${status}`;
}

/** The four-stage decision payload; `request_id` makes retries idempotent. */
function decisionBody(action: ReviewAction, reasonTags: ReasonTag[] = []) {
  return JSON.stringify({
    request_id:
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    action,
    reason_tags: reasonTags,
  });
}

export const api = {
  /** Undecided candidates, already ordered by review priority server-side. */
  async queue(): Promise<Candidate[]> {
    const body = await request<{ items?: Candidate[] }>("/v1/review-queue");
    return body.items ?? [];
  },

  async candidate(candidateId: string): Promise<CandidateContext> {
    return request<CandidateContext>(
      `/v1/candidates/${encodeURIComponent(candidateId)}/review-context`,
    );
  },

  async overview(): Promise<DiscoveryOverview> {
    return request<DiscoveryOverview>("/v1/discovery/overview");
  },

  async log(tail = 240): Promise<{ exists: boolean; lines: string[] }> {
    return request<{ exists: boolean; lines: string[] }>(
      `/v1/discovery/log?tail=${tail}`,
    );
  },

  async decide(
    candidateId: string,
    version: number,
    action: ReviewAction,
    actorId: string,
    reasonTags: ReasonTag[] = [],
  ): Promise<void> {
    await request(
      `/v1/candidates/${encodeURIComponent(candidateId)}/versions/${version}/decisions`,
      {
        method: "POST",
        headers: { ...JSON_HEADERS, "X-Actor-ID": actorId },
        body: decisionBody(action, reasonTags),
      },
    );
  },

  async revoke(
    candidateId: string,
    version: number,
    decisionId: string,
    actorId: string,
    reason = "",
  ): Promise<void> {
    await request(
      `/v1/candidates/${encodeURIComponent(candidateId)}/versions/${version}/decisions/${encodeURIComponent(decisionId)}/revoke`,
      {
        method: "POST",
        headers: { ...JSON_HEADERS, "X-Actor-ID": actorId },
        body: JSON.stringify({
          request_id:
            typeof crypto !== "undefined" && "randomUUID" in crypto
              ? crypto.randomUUID()
              : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          reason,
        }),
      },
    );
  },

  async runDiscovery(maxProbes = 20): Promise<DiscoveryRunSummary> {
    return request<DiscoveryRunSummary>("/v1/run/discovery", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ max_probes: maxProbes }),
    });
  },
};
