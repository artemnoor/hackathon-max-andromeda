import { createLogger } from '../../shared/logger.js';

const logger = createLogger('news.carousel');
const boundCarousels = new WeakSet();
const carouselControllers = new WeakMap();
const SLIDE_DURATION = 8500;

export function bindNewsCarousel(pageRoot) {
  const carousel = pageRoot?.matches?.('[data-news-carousel]')
    ? pageRoot
    : pageRoot?.querySelector?.('[data-news-carousel]');
  const viewport = carousel?.querySelector('[data-news-viewport]');
  const track = carousel?.querySelector('[data-news-track]');
  const liveRegion = carousel?.querySelector('[data-news-status]');
  const windowRef = pageRoot?.defaultView || pageRoot?.ownerDocument?.defaultView || globalThis.window;
  if (!carousel || !viewport || !track || !windowRef || boundCarousels.has(carousel)) return;

  let slides = [...track.querySelectorAll('.news-card')];
  let newsCount = Number(carousel.dataset.newsCount);
  if (newsCount < 2 || slides.length !== newsCount * 3) return;

  const reducedMotion = windowRef.matchMedia('(prefers-reduced-motion: reduce)');
  const page = carousel.closest('.page');
  let currentIndex = newsCount;
  let animationFrame = null;
  let progressStart = null;
  let elapsedBeforePause = 0;
  let hovered = false;
  let focusWithin = false;
  let dragging = false;
  let suppressClick = false;
  let dragStartX = 0;
  let dragDelta = 0;
  let pageActive = page?.classList.contains('active') ?? true;

  function targetX(index) {
    const slideWidth = slides[0].offsetWidth;
    const gap = Number.parseFloat(windowRef.getComputedStyle(track).columnGap) || 0;
    return viewport.clientWidth / 2 - slideWidth / 2 - index * (slideWidth + gap);
  }

  function setTrackPosition(index, animate = true, extra = 0) {
    if (animate) track.style.removeProperty('transition');
    else track.style.transition = 'none';
    track.style.transform = `translate3d(${targetX(index) + extra}px, 0, 0)`;
  }

  function updateActiveSlide() {
    slides.forEach((slide, index) => {
      const isActive = index === currentIndex;
      slide.classList.toggle('active', isActive);
      slide.setAttribute('aria-hidden', String(!isActive));
      slide.querySelectorAll('a[href], button, [tabindex]').forEach((element) => {
        element.tabIndex = isActive ? 0 : -1;
      });
    });
  }

  function announceCurrentSlide() {
    if (!liveRegion) return;
    const activeSlide = slides[currentIndex];
    const realIndex = Number(activeSlide?.dataset.realIndex) || 0;
    const title = activeSlide?.querySelector('h3')?.textContent || '';
    liveRegion.textContent = `Новость ${realIndex + 1} из ${newsCount}: ${title}`;
  }

  function normalizeIndex() {
    const normalizedIndex = newsCount + ((currentIndex % newsCount) + newsCount) % newsCount;
    if (normalizedIndex === currentIndex) return;

    currentIndex = normalizedIndex;
    setTrackPosition(currentIndex, false);
    track.getBoundingClientRect();
    track.style.removeProperty('transition');
    updateActiveSlide();
  }

  function canAdvance() {
    return !reducedMotion.matches
      && !hovered
      && !focusWithin
      && !windowRef.document.hidden
      && pageActive;
  }

  function pauseProgress() {
    if (animationFrame !== null) {
      windowRef.cancelAnimationFrame(animationFrame);
      animationFrame = null;
    }
    if (progressStart !== null) {
      elapsedBeforePause = Math.min(SLIDE_DURATION, windowRef.performance.now() - progressStart);
      progressStart = null;
    }
  }

  function updateProgress(timestamp) {
    animationFrame = null;
    if (!canAdvance()) {
      pauseProgress();
      return;
    }

    if (progressStart === null) progressStart = timestamp - elapsedBeforePause;
    elapsedBeforePause = Math.min(timestamp - progressStart, SLIDE_DURATION);

    const progressBar = slides[currentIndex]?.querySelector('.news-progress-bar');
    if (progressBar) progressBar.style.transform = `scaleX(${elapsedBeforePause / SLIDE_DURATION})`;

    if (elapsedBeforePause >= SLIDE_DURATION) {
      elapsedBeforePause = 0;
      progressStart = null;
      moveTo(currentIndex + 1, { announce: false, source: 'autoplay' });
      return;
    }

    animationFrame = windowRef.requestAnimationFrame(updateProgress);
  }

  function syncProgress(reset = false) {
    if (reset) {
      pauseProgress();
      elapsedBeforePause = 0;
      slides.forEach((slide) => {
        const progressBar = slide.querySelector('.news-progress-bar');
        if (progressBar) progressBar.style.transform = 'scaleX(0)';
      });
    }
    if (!canAdvance()) {
      pauseProgress();
      return;
    }
    if (animationFrame === null) animationFrame = windowRef.requestAnimationFrame(updateProgress);
  }

  function moveTo(index, { announce = true, source = 'interaction' } = {}) {
    pauseProgress();
    const stepCount = index - currentIndex;
    if (currentIndex < newsCount || currentIndex >= newsCount * 2) normalizeIndex();
    index = currentIndex + stepCount;
    if (index < 0 || index >= slides.length) {
      index = newsCount + ((index % newsCount) + newsCount) % newsCount;
    }
    currentIndex = index;
    updateActiveSlide();
    setTrackPosition(currentIndex, true);
    if (announce) announceCurrentSlide();
    logger.debug('slide_changed', { id: slides[currentIndex]?.dataset.newsId, source });

    if (reducedMotion.matches) {
      normalizeIndex();
      syncProgress(true);
    }
  }

  function replaceSlides(markup, count) {
    pauseProgress();
    track.innerHTML = markup;
    newsCount = Number(count) || 0;
    carousel.dataset.newsCount = String(newsCount);
    slides = [...track.querySelectorAll('.news-card')];
    if (slides.length !== newsCount * 3 || newsCount < 2) return;
    currentIndex = newsCount;
    updateActiveSlide();
    setTrackPosition(currentIndex, false);
    track.getBoundingClientRect();
    track.style.removeProperty('transition');
    syncProgress(true);
    announceCurrentSlide();
  }

  function finishTransition(event) {
    if (event.target !== track || event.propertyName !== 'transform') return;
    normalizeIndex();
    syncProgress(true);
  }

  function pointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    if (currentIndex < newsCount || currentIndex >= newsCount * 2) normalizeIndex();
    dragging = true;
    suppressClick = false;
    dragStartX = event.clientX;
    dragDelta = 0;
    viewport.classList.add('dragging');
    pauseProgress();
    setTrackPosition(currentIndex, false);
    viewport.setPointerCapture?.(event.pointerId);
  }

  function pointerMove(event) {
    if (!dragging) return;
    dragDelta = event.clientX - dragStartX;
    if (Math.abs(dragDelta) > 5) suppressClick = true;
    setTrackPosition(currentIndex, false, dragDelta);
  }

  function pointerUp(event) {
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove('dragging');
    const threshold = Math.min(90, slides[0].offsetWidth * .2);
    if (dragDelta <= -threshold) moveTo(currentIndex + 1, { source: 'swipe' });
    else if (dragDelta >= threshold) moveTo(currentIndex - 1, { source: 'swipe' });
    else if (Math.abs(dragDelta) <= 1) syncProgress();
    else setTrackPosition(currentIndex, true);
    dragDelta = 0;
    windowRef.setTimeout(() => { suppressClick = false; }, 0);
    try { viewport.releasePointerCapture?.(event.pointerId); } catch {}
  }

  carousel.addEventListener('click', (event) => {
    if (suppressClick) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const slide = event.target.closest('.news-card');
    if (!slide || event.target.closest('a[href]')) return;
    const selectedIndex = Number(slide.dataset.index);
    if (Number.isInteger(selectedIndex) && selectedIndex !== currentIndex) {
      moveTo(selectedIndex, { source: 'adjacent-slide' });
    }
  });

  track.addEventListener('transitionend', finishTransition);
  viewport.addEventListener('pointerdown', pointerDown);
  viewport.addEventListener('pointermove', pointerMove);
  viewport.addEventListener('pointerup', pointerUp);
  viewport.addEventListener('pointercancel', pointerUp);
  carousel.addEventListener('pointerenter', () => { hovered = true; syncProgress(); });
  carousel.addEventListener('pointerleave', () => { hovered = false; syncProgress(); });
  carousel.addEventListener('focusin', () => { focusWithin = true; syncProgress(); });
  carousel.addEventListener('focusout', () => {
    windowRef.setTimeout(() => {
      focusWithin = carousel.contains(windowRef.document.activeElement);
      syncProgress();
    }, 0);
  });
  windowRef.document.addEventListener('visibilitychange', () => syncProgress());
  windowRef.addEventListener('resize', () => {
    setTrackPosition(currentIndex, false);
    track.getBoundingClientRect();
    track.style.removeProperty('transition');
    syncProgress(true);
  });
  reducedMotion.addEventListener('change', () => syncProgress(true));

  if (page && windowRef.MutationObserver) {
    const pageObserver = new windowRef.MutationObserver(() => {
      const isActive = page.classList.contains('active');
      if (isActive && !pageActive) {
        setTrackPosition(currentIndex, false);
        track.getBoundingClientRect();
        track.style.removeProperty('transition');
      }
      pageActive = isActive;
      syncProgress();
    });
    pageObserver.observe(page, { attributes: true, attributeFilter: ['class'] });
  }

  currentIndex = newsCount;
  updateActiveSlide();
  setTrackPosition(currentIndex, false);
  slides[currentIndex]?.querySelector('.news-progress-bar')?.style.setProperty('transform', 'scaleX(0)');
  syncProgress();
  boundCarousels.add(carousel);
  carouselControllers.set(carousel, { replaceSlides });
}

export function updateNewsCarousel(carousel, { cardsMarkup, count } = {}) {
  if (!carousel) return;
  carouselControllers.get(carousel)?.replaceSlides(cardsMarkup, count);
}
