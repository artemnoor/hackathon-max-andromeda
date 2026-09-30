import { createLogger } from '../shared/logger.js';

const logger = createLogger('navigation');
const primarySectionForPage = Object.freeze({
  home: 'home',
  catalog: 'catalog',
  program: 'catalog',
  'admission-check': 'catalog',
  shortlist: 'shortlist',
  compare: 'compare',
  profile: 'profile',
  proftest: 'profile',
  recommendations: 'profile',
  rules: 'profile',
  news: 'profile',
  olympiads: 'profile',
  'personal-route': 'profile',
});

export function createNavigator(routeHandlers, root = globalThis.document) {
  function openPage(page, options = {}) {
    logger.debug('route.start', { page });
    root.querySelectorAll('.page').forEach((element) => element.classList.remove('active'));
    const pageElement = root.getElementById(`page-${page}`);
    if (!pageElement) {
      logger.warn('route.not_found', { page });
      return false;
    }

    pageElement.classList.add('active');
    const primaryPage = primarySectionForPage[page] || page;
    root.querySelectorAll('.nav button').forEach((button) => {
      const isCurrentPage = button.dataset.page === primaryPage;
      button.classList.toggle('active', isCurrentPage);
      if (isCurrentPage) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });

    root.querySelectorAll('.sidebar .nav-section').forEach((section) => {
      section.removeAttribute('data-current');
    });
    const activeNavItem = [...root.querySelectorAll('.sidebar .nav-leaf')]
      .find((button) => button.dataset.page === primaryPage);
    const activeNavSection = activeNavItem?.closest('.nav-section');
    if (activeNavSection) {
      activeNavSection.setAttribute('data-current', '');
      activeNavSection.setAttribute('data-open', '');
      activeNavSection.querySelector('[data-nav-toggle]')?.setAttribute('aria-expanded', 'true');
      activeNavSection.querySelectorAll('.nav-leaf').forEach((button) => { button.tabIndex = 0; });

      const tree = activeNavItem.closest('.nav-tree');
      const itemIndex = [...tree.querySelectorAll('.nav-leaf')].indexOf(activeNavItem);
      tree.style.setProperty('--nav-active-height', `${itemIndex * 36}px`);
    }

    try {
      const result = routeHandlers[page]?.(options);
      if (result && typeof result.then === 'function') {
        result.catch((error) => logger.error('route.render_failed', { page, errorName: error.name }));
      }
    } catch (error) {
      logger.error('route.render_failed', { page, errorName: error.name });
      throw error;
    }

    globalThis.window?.scrollTo?.({ top: 0, behavior: 'smooth' });
    logger.debug('route.complete', { page });
    return true;
  }

  return Object.freeze({ openPage });
}
