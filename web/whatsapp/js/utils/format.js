/**
 * format.js - Format WhatsApp text with Markdown and Safe Links
 */

import { escapeHtml } from './escape.js';
import { isSafeUrl } from './safe-url.js';

export function formatWhatsAppText(raw) {
  if (!raw) return '';
  let safe = escapeHtml(raw);

  // Triple backtick code blocks
  safe = safe.replace(/```([^`]+)```/g, '<code class="wa-code-block">$1</code>');

  // Bold (*text*)
  safe = safe.replace(/\*([^*\n]+)\*/g, '<strong>$1</strong>');

  // Italic (_text_)
  safe = safe.replace(/_([^_\n]+)_/g, '<em>$1</em>');

  // Strikethrough (~text~)
  safe = safe.replace(/~([^~\n]+)~/g, '<del>$1</del>');

  // Monospace (`text`)
  safe = safe.replace(/`([^`\n]+)`/g, '<code class="wa-code-inline">$1</code>');

  // Safe HTTP/HTTPS links
  safe = safe.replace(/(https?:\/\/[^\s<]+)/g, (url) => {
    if (isSafeUrl(url)) {
      return `<a href="${url}" target="_blank" rel="noopener noreferrer" style="color:#53bdeb;text-decoration:underline;">${url}</a>`;
    }
    return url;
  });

  // Line breaks
  safe = safe.replace(/\n/g, '<br>');

  return safe;
}
