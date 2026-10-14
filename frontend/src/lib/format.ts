/** Small pure formatters. No locale guessing — the console is bilingual. */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

type RelativeDict = {
  minutesOld: string;
  hoursOld: string;
  daysOld: string;
  monthsOld: string;
  yearsOld: string;
};

/** "3h ago" style relative time, bucketed so the label stays short. */
export function relativeTime(
  value: string | null | undefined,
  now: number,
  dict: RelativeDict,
  fill: (template: string, values: Record<string, string | number>) => string,
): string {
  const parsed = parseTime(value);
  if (parsed === null) return "—";
  const delta = Math.max(0, now - parsed);
  if (delta < HOUR) return fill(dict.minutesOld, { n: Math.max(1, Math.round(delta / MINUTE)) });
  if (delta < DAY) return fill(dict.hoursOld, { n: Math.round(delta / HOUR) });
  if (delta < 30 * DAY) return fill(dict.daysOld, { n: Math.round(delta / DAY) });
  if (delta < 365 * DAY) return fill(dict.monthsOld, { n: Math.round(delta / (30 * DAY)) });
  return fill(dict.yearsOld, { n: (delta / (365 * DAY)).toFixed(1) });
}

/** Absolute timestamp for tooltips and the audit trail. */
export function absoluteTime(value: string | null | undefined): string {
  const parsed = parseTime(value);
  if (parsed === null) return "—";
  const date = new Date(parsed);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Time of day only — used inside the log drawer. */
export function clockTime(value: string | null | undefined): string {
  const parsed = parseTime(value);
  if (parsed === null) return "—";
  const date = new Date(parsed);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

/** Priority is a 0–1 score; two decimals is the resolution the formula keeps. */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(2);
}

export function formatPercent(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return `${Math.round(value * 100)}`;
}

/** Domains read as identifiers, so they keep their own casing and width. */
export function displayDomain(domain: string): string {
  return domain.replace(/^www\./, "");
}
