export const canonicalOpenApiPath: string;
export const generatedClientDirectory: string;
export const generatedClientFiles: readonly string[];

export function generateClientArtifacts(options?: {
  specPath?: string;
  outputDirectory?: string;
}): Promise<string>;

export function detectClientDrift(options?: {
  specPath?: string;
  expectedDirectory?: string;
}): Promise<string[]>;
