import type { NextConfig } from "next";

const isolatedDevDistDir = process.env.ANDROMEDA_NEXT_DEV_DIST_DIR;
const isolatedDevTsconfig = process.env.ANDROMEDA_NEXT_DEV_TSCONFIG_PATH;
if (isolatedDevDistDir && !/^\.next-smoke-[a-zA-Z0-9_-]+$/.test(isolatedDevDistDir)) {
  throw new Error("ANDROMEDA_NEXT_DEV_DIST_DIR must be a generated .next-smoke-* directory name");
}
if (isolatedDevTsconfig && !/^tsconfig-smoke-[a-zA-Z0-9_-]+\.json$/.test(isolatedDevTsconfig)) {
  throw new Error("ANDROMEDA_NEXT_DEV_TSCONFIG_PATH must be a generated tsconfig-smoke-*.json filename");
}

const nextConfig: NextConfig = {
  output: "standalone",
  ...(process.env.NODE_ENV === "development" && isolatedDevDistDir
    ? { distDir: isolatedDevDistDir }
    : {}),
  ...(process.env.NODE_ENV === "development" && isolatedDevTsconfig
    ? { typescript: { tsconfigPath: isolatedDevTsconfig } }
    : {}),
  reactStrictMode: false,
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

if (process.env.NODE_ENV === "development") {
  console.info("[FIX:frontend-origin] Next dev origins enabled for localhost and 127.0.0.1");
  if (isolatedDevDistDir && isolatedDevTsconfig) {
    console.info("[FIX:isolated-next-smoke] using isolated temporary dev output and TypeScript config");
  }
}

export default nextConfig;
