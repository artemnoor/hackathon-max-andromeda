export const MAX_BRIDGE_SCRIPT = 'https://st.max.ru/js/max-web-app.js';

export const miniAppContentSecurityPolicy = (): string => [
  "default-src 'self'",
  "script-src 'self' https://st.max.ru",
  "style-src 'self'",
  "connect-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors https://max.ru https://web.max.ru",
  "form-action 'self'",
].join('; ');
