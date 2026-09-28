import { ImageResponse } from "next/og";
import { loadOgFonts } from "./fonts";

export async function ogResponse(element: React.ReactElement, width = 1200, height = 760): Promise<ImageResponse> {
  return new ImageResponse(element, { width, height, fonts: await loadOgFonts() });
}
