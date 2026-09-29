import { readFile } from "node:fs/promises";
import path from "node:path";

let cachedFonts: Promise<{ name: string; data: ArrayBuffer; weight: 400 | 700; style: "normal" }[]> | undefined;

export function loadOgFonts() {
  cachedFonts ??= Promise.all([
    readFont("NotoSans-Regular.ttf", 400),
    readFont("NotoSans-Bold.ttf", 700),
  ]);
  return cachedFonts;
}

async function readFont(name: string, weight: 400 | 700) {
  const buffer = await readFile(path.join(process.cwd(), "public", "fonts", name));
  return { name: "Noto Sans", data: buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength), weight, style: "normal" as const };
}
