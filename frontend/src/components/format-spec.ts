/**
 * Spec rows need one thing the raw column list cannot give them: money amounts are
 * stored as an `*_amount` column beside an `*_currency` column, and a figure shown
 * without its currency is a procurement hazard. These helpers pair them and suppress
 * the currency row that would otherwise repeat the same fact.
 */
import { fieldValue, money } from "@/lib/format";
import { labelFor } from "@/lib/labels";

type SpecRecord = Record<string, unknown>;

const AMOUNT_SUFFIX = "_amount";
const CURRENCY_SUFFIX = "_currency";

/** True for a column that only exists to qualify a sibling amount. */
export function isCurrencyCompanion(field: string, spec: SpecRecord): boolean {
  if (!field.endsWith(CURRENCY_SUFFIX)) return false;
  const amount = `${field.slice(0, -CURRENCY_SUFFIX.length)}${AMOUNT_SUFFIX}`;
  return amount in spec;
}

/** The displayed value for a spec field, with money shown in its own currency. */
export function specValue(
  field: string,
  value: unknown,
  spec: SpecRecord,
): string {
  if (field.endsWith(AMOUNT_SUFFIX) && typeof value === "number") {
    const currency =
      spec[`${field.slice(0, -AMOUNT_SUFFIX.length)}${CURRENCY_SUFFIX}`];
    return money(
      value,
      typeof currency === "string" && currency ? currency : "USD",
    );
  }
  if (typeof value === "string" && value && /^[a-z0-9_]+$/.test(value)) {
    return labelFor(field, value);
  }
  return fieldValue(field, value);
}
