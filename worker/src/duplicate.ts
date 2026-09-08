export type DuplicateKv = Pick<KVNamespace, "get" | "put">;

type JsonObject = Record<string, unknown>;

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as JsonObject)
        .filter(([key]) => !["reportId", "testedAt", "summary", "notes"].includes(key))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, child]) => [key, stable(child)]),
    );
  }
  return value;
}

export async function duplicateFingerprint(report: JsonObject): Promise<string> {
  const canonical = JSON.stringify(stable(report));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest)).map(v => v.toString(16).padStart(2, "0")).join("");
}

export async function claimSubmission(
  kv: DuplicateKv | undefined,
  report: JsonObject,
  ttlSeconds = 7 * 24 * 60 * 60,
): Promise<{duplicate: boolean; fingerprint: string}> {
  const fingerprint = await duplicateFingerprint(report);
  if (!kv) return {duplicate: false, fingerprint};
  const key = `duplicate:${fingerprint}`;
  if (await kv.get(key)) return {duplicate: true, fingerprint};
  // KV is eventually consistent, so this is an abuse/accidental-repeat guard rather than a
  // uniqueness primitive. Scoring still independently deduplicates merged reports.
  await kv.put(key, "1", {expirationTtl: ttlSeconds});
  return {duplicate: false, fingerprint};
}
