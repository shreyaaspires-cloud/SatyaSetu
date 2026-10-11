/**
 * Safe URL validation and sanitization utility.
 * Enforces http: and https: protocols only to eliminate javascript: / data: / vbscript: XSS vectors.
 */

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * Validates whether a URL uses an allowed HTTP/HTTPS protocol.
 * @param {string} urlString
 * @returns {boolean}
 */
export function isSafeUrl(urlString) {
  if (!urlString || typeof urlString !== "string") return false;
  const trimmed = urlString.trim();
  if (!trimmed) return false;

  try {
    const parsed = new URL(trimmed, window.location.origin);
    return ALLOWED_PROTOCOLS.has(parsed.protocol);
  } catch {
    return false;
  }
}

/**
 * Returns a sanitized URL string, or "#" if the URL is unsafe or invalid.
 * @param {string} urlString
 * @returns {string}
 */
export function sanitizeUrl(urlString) {
  if (!isSafeUrl(urlString)) return "#";
  try {
    const parsed = new URL(urlString.trim(), window.location.origin);
    return parsed.href;
  } catch {
    return "#";
  }
}
