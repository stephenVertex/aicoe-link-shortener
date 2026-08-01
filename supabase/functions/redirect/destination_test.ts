import { buildDestinationUrl } from "./destination.ts";

function assertEquals(actual: unknown, expected: unknown): void {
  if (actual !== expected) {
    throw new Error(
      `Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

Deno.test("Substack destinations keep UTM parameters but omit internal ref", () => {
  const url = buildDestinationUrl(
    "https://trilogyai.substack.com/p/minimax-h3-ai-video?existing=yes",
    {
      utm_source: "whatsapp",
      utm_medium: "social",
      utm_campaign: "minimax-h3-ai-video",
      utm_content: "machine-cinema",
      utm_term: "video",
      ref: "leo",
    },
  );

  assertEquals(url.searchParams.get("existing"), "yes");
  assertEquals(url.searchParams.get("utm_source"), "whatsapp");
  assertEquals(url.searchParams.get("utm_medium"), "social");
  assertEquals(url.searchParams.get("utm_campaign"), "minimax-h3-ai-video");
  assertEquals(url.searchParams.get("utm_content"), "machine-cinema");
  assertEquals(url.searchParams.get("utm_term"), "video");
  assertEquals(url.searchParams.has("ref"), false);
});

Deno.test("Substack destinations remove a ref already stored in the destination", () => {
  const url = buildDestinationUrl(
    "https://substack.com/home/post/p-123?ref=legacy",
    {},
  );

  assertEquals(url.searchParams.has("ref"), false);
});

Deno.test("nested Substack hosts omit internal ref", () => {
  const url = buildDestinationUrl(
    "https://news.team.substack.com/p/example",
    { ref: "stephen" },
  );

  assertEquals(url.searchParams.has("ref"), false);
});

Deno.test("non-Substack destinations retain internal ref behavior", () => {
  const url = buildDestinationUrl(
    "https://example.com/article?existing=yes",
    { utm_source: "linkedin", ref: "stephen" },
  );

  assertEquals(url.searchParams.get("existing"), "yes");
  assertEquals(url.searchParams.get("utm_source"), "linkedin");
  assertEquals(url.searchParams.get("ref"), "stephen");
});

Deno.test("lookalike domains are not treated as Substack", () => {
  const url = buildDestinationUrl(
    "https://substack.com.example.net/article",
    { ref: "stephen" },
  );

  assertEquals(url.searchParams.get("ref"), "stephen");
});
