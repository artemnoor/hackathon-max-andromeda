import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ErrorState, Loading, ProvenanceChip, safeExternalHref } from "./shared";

describe("shared source and state primitives", () => {
  it("only renders safe HTTP(S) provenance links", () => {
    expect(safeExternalHref("javascript:alert(1)")).toBeNull();
    expect(safeExternalHref("https://example.test/source")).toBe("https://example.test/source");

    const unsafe = renderToStaticMarkup(<ProvenanceChip prov={{ sourceName: "Источник", sourceUrl: "javascript:alert(1)" }} />);
    const safe = renderToStaticMarkup(<ProvenanceChip prov={{ sourceName: "Источник", sourceUrl: "https://example.test/source" }} />);
    expect(unsafe).not.toContain("href=");
    expect(safe).toContain('href="https://example.test/source"');
  });

  it("exposes loading and failure states as live regions", () => {
    expect(renderToStaticMarkup(<Loading label="Загрузка" />)).toContain('role="status"');
    expect(renderToStaticMarkup(<ErrorState title="Ошибка" message="Повторите" />)).toContain('role="alert"');
  });
});
