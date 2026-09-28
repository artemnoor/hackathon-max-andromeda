import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

const projectRoot = process.cwd();
const nextRoot = join(projectRoot, ".next");
const standaloneRoot = join(nextRoot, "standalone");

if (!existsSync(standaloneRoot)) {
  throw new Error("Next standalone output was not created");
}

const standaloneNextRoot = join(standaloneRoot, ".next");
mkdirSync(standaloneNextRoot, { recursive: true });

const standaloneStatic = join(standaloneNextRoot, "static");
rmSync(standaloneStatic, { recursive: true, force: true });
cpSync(join(nextRoot, "static"), standaloneStatic, { recursive: true });

const standalonePublic = join(standaloneRoot, "public");
rmSync(standalonePublic, { recursive: true, force: true });
if (existsSync(join(projectRoot, "public"))) {
  cpSync(join(projectRoot, "public"), standalonePublic, { recursive: true });
}

console.log("Prepared Next standalone assets");
