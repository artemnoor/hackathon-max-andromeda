export function el(id, root = globalThis.document) {
  if (!root?.getElementById) return null;
  return root.getElementById(id);
}

export function setHtml(element, html) {
  if (!element) throw new TypeError('Cannot render HTML into a missing element');
  element.innerHTML = html;
}

const htmlEscapes = Object.freeze({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
});

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => htmlEscapes[character]);
}

export function safeHttpUrl(value) {
  try {
    const url = new URL(String(value), globalThis.location?.origin || 'https://localhost');
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}
