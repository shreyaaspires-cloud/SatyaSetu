/**
 * Safe HTML string escaping utility to prevent XSS.
 */

const HTML_ENTITY_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
  "/": "&#x2F;",
  "`": "&#x60;",
  "=": "&#x3D;",
};

/**
 * Escapes characters in a string for safe HTML insertion.
 * @param {unknown} val
 * @returns {string}
 */
export function escapeHtml(val) {
  if (val === null || val === undefined) return "";
  return String(val).replace(/[&<>"'`=\/]/g, (s) => HTML_ENTITY_MAP[s] || s);
}

/**
 * Safely creates a text node or sets textContent on a DOM element.
 * @param {HTMLElement} el
 * @param {string} text
 */
export function setText(el, text) {
  if (el) {
    el.textContent = text == null ? "" : String(text);
  }
}
