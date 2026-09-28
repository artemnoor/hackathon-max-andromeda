export type OgTheme = "light" | "dark";

export type OgPalette = {
  background: string;
  foreground: string;
  muted: string;
  border: string;
  primary: string;
  secondary: string;
  warning: string;
  card: string;
};

export const PALETTES: Record<OgTheme, OgPalette> = {
  light: {
    background: "#f8f6f0",
    foreground: "#3d3933",
    muted: "#746e65",
    border: "#e5ded2",
    primary: "#c56b3f",
    secondary: "#167866",
    warning: "#b26a16",
    card: "#ffffff",
  },
  dark: {
    background: "#302d29",
    foreground: "#f7f1e7",
    muted: "#b9afa1",
    border: "#5b554c",
    primary: "#e29163",
    secondary: "#67c2ae",
    warning: "#e5a65b",
    card: "#403b35",
  },
};

export function parseTheme(value: string | null): OgTheme {
  return value === "dark" ? "dark" : "light";
}
