/** @typedef {{ initData?: unknown }} MaxWebAppBridge */

/** @returns {MaxWebAppBridge|null} */
export function getMaxBridge() {
  const candidate = window.WebApp;
  return candidate && typeof candidate === 'object' ? candidate : null;
}

/** @returns {string} Opaque launch proof; never use initDataUnsafe. */
export function getInitData() {
  const value = getMaxBridge()?.initData;
  return typeof value === 'string' ? value : '';
}
