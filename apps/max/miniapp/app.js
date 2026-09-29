import { getInitData, getMaxBridge } from './bridge.js';

const status = document.querySelector('#status');
const mark = document.querySelector('.status-mark');

const show = (message, verified = false) => {
  if (status) status.textContent = message;
  if (mark) mark.dataset.state = verified ? 'verified' : 'unverified';
};

const bridge = getMaxBridge();
if (!bridge) {
  show('Это preview оболочки. Откройте Mini App из MAX для проверки запуска.');
} else {
  const initData = getInitData();
  if (!initData) {
    show('MAX не передал данные запуска. Закройте и снова откройте Mini App из MAX.');
  } else {
    try {
      const response = await fetch('/api/max/session', {
        method: 'GET',
        headers: { 'X-Max-Init-Data': initData },
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
      });
      const result = response.ok ? await response.json() : undefined;
      if (result?.authenticated === true) {
        show('Подпись запуска MAX проверена. Аккаунт Andromeda не подключён.', true);
      } else {
        show('Не удалось проверить запуск. Закройте и снова откройте Mini App из MAX.');
      }
    } catch {
      show('Проверка запуска сейчас недоступна. Попробуйте открыть Mini App позже.');
    }
  }
}
