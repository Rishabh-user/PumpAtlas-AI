import { num } from "@/lib/format";

/**
 * A duty figure, or the envelope it sits inside.
 *
 * A pump model is a family — ECPJ comes in 45 sizes — so its datasheet states a
 * performance envelope, "flow to 1,000 m³/h, head to 150 m", not a single rated point.
 * A rated capacity only exists once a size has been chosen against a duty.
 *
 * The list asked `search_index` for `rated_capacity_m3h` and printed an em dash when it
 * was null, which it is for 56 of the 78 records that hold a maximum. Nine out of ten
 * blank capacity cells were blank because the column was the wrong one to ask.
 */

export interface Envelope {
  rated?: number | string | null;
  min?: number | string | null;
  max?: number | string | null;
}

const EM_DASH = "—";

function value(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const parsed = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export function dutyText(
  envelope: Envelope | null | undefined,
  decimals = 0,
): string {
  if (!envelope) return EM_DASH;
  const rated = value(envelope.rated);
  // A rated figure is the real answer; the envelope is only the fallback.
  if (rated !== null) return num(rated, { decimals });

  const low = value(envelope.min);
  const high = value(envelope.max);
  if (low !== null && high !== null) {
    return `${num(low, { decimals })}–${num(high, { decimals })}`;
  }
  if (high !== null) return `≤ ${num(high, { decimals })}`;
  if (low !== null) return `≥ ${num(low, { decimals })}`;
  return EM_DASH;
}

/**
 * The cell contents. A value derived from the envelope is dimmed, because "this family
 * reaches 1,000" is a weaker statement than "this pump is rated for 1,000" and a buyer
 * comparing a column of numbers should be able to see which is which at a glance.
 */
export function Duty({
  envelope,
  decimals = 0,
}: {
  envelope: Envelope | null | undefined;
  decimals?: number;
}) {
  const text = dutyText(envelope, decimals);
  const isRated = value(envelope?.rated) !== null;
  if (text === EM_DASH) return <span className="text-muted-foreground">{EM_DASH}</span>;
  return (
    <span
      className={isRated ? undefined : "text-muted-foreground"}
      title={isRated ? undefined : "The range this model family covers, not a rated duty point"}
    >
      {text}
    </span>
  );
}
