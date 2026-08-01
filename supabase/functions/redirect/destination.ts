export interface TrackingParameters {
  utm_source?: string | null;
  utm_medium?: string | null;
  utm_campaign?: string | null;
  utm_content?: string | null;
  utm_term?: string | null;
  ref?: string | null;
}

function isSubstackHostname(hostname: string): boolean {
  const normalizedHostname = hostname.toLowerCase().replace(/\.$/, "");
  return normalizedHostname === "substack.com" ||
    normalizedHostname.endsWith(".substack.com");
}

/**
 * Add tracking parameters to a destination without exposing our internal
 * person reference through query parameters reserved by the destination.
 */
export function buildDestinationUrl(
  destinationUrl: string,
  tracking: TrackingParameters,
): URL {
  const url = new URL(destinationUrl);

  if (tracking.utm_source) {
    url.searchParams.set("utm_source", tracking.utm_source);
  }
  if (tracking.utm_medium) {
    url.searchParams.set("utm_medium", tracking.utm_medium);
  }
  if (tracking.utm_campaign) {
    url.searchParams.set("utm_campaign", tracking.utm_campaign);
  }
  if (tracking.utm_content) {
    url.searchParams.set("utm_content", tracking.utm_content);
  }
  if (tracking.utm_term) {
    url.searchParams.set("utm_term", tracking.utm_term);
  }

  if (isSubstackHostname(url.hostname)) {
    // Substack reserves `ref` for its own client-side routing. Arbitrary values
    // cause valid articles to be replaced by its "page croaked" error screen.
    url.searchParams.delete("ref");
  } else if (tracking.ref) {
    url.searchParams.set("ref", tracking.ref);
  }

  return url;
}
