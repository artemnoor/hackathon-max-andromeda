import { createJevTree } from "jev-tree";

const input = JSON.parse(await readStdin());
const candidates = new Map(input.candidates.map((candidate) => [candidate.canonical_id, candidate]));
const candidateIds = [...candidates.keys()];

function shape(node) {
  const children = [
    ...(node.children ?? []).map(shape),
    ...(node.candidate_ids ?? []).map((id) => ({
      id,
      label: candidates.get(id)?.label ?? id,
      value: id,
    })),
  ];
  return {
    id: node.node_id,
    label: node.node_id,
    ...(children.length ? { children } : {}),
  };
}

try {
  const tree = createJevTree({
    maxFanout: input.maxFanout,
    maxDepth: input.maxDepth,
    maxCalls: input.maxCalls,
    timeoutMs: input.timeoutMs,
  });
  const result = await tree.select({
    state: input.query,
    question: `Which canonical ${input.entityType} best matches the query?`,
    shape: shape(input.tree.root),
  });
  const selectedId = [...(result.ids ?? [])].reverse().find((id) => candidates.has(id)) ?? null;
  process.stdout.write(JSON.stringify({
    selectedId,
    candidateHash: input.candidateHash ?? null,
    reason: result.reason ?? (selectedId ? "model" : "unavailable"),
  }));
} catch {
  process.stdout.write(JSON.stringify({ selectedId: null, candidateHash: input.candidateHash ?? null, reason: "unavailable" }));
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { data += chunk; });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}
