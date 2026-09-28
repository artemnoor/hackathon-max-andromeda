import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, stable(nested)]),
    );
  }
  return value;
}

const freshPath = process.env.OPENAPI_FILE;
const snapshotPath = process.env.OPENAPI_SNAPSHOT;
if (!freshPath || !snapshotPath) {
  throw new Error("Set OPENAPI_FILE and OPENAPI_SNAPSHOT to compare OpenAPI snapshots.");
}

const fresh = JSON.parse(await readFile(resolve(freshPath), "utf8"));
const snapshot = JSON.parse(await readFile(resolve(snapshotPath), "utf8"));
if (JSON.stringify(stable(fresh)) !== JSON.stringify(stable(snapshot))) {
  throw new Error(`OpenAPI snapshot is stale: ${resolve(snapshotPath)} does not match ${resolve(freshPath)}.`);
}
console.log(`OpenAPI snapshot ${resolve(snapshotPath)} matches ${resolve(freshPath)}.`);
