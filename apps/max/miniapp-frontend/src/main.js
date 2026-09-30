import { programs } from './data/programs.js';
import { interestQuestions } from './data/interest-questions.js';
import { cacheRemotePrograms, getAvailablePrograms, getProgramById, catalogRepository } from './app/repository.js';
import { state, updateState, subscribeToState } from './app/state.js';
import { createNavigator } from './app/navigation.js';
import { updateShellStats } from './app/shell.js';
import { formatMoney } from './shared/formatters.js';
import { renderProgramCard } from './shared/components/program-card.js';
import { showToast } from './shared/components/toast.js';
import { handleAssistantClick } from './shared/components/assistant-dialog.js';
import { createLogger } from './shared/logger.js';
import { mountHugeicons } from './shared/icons.js';
import { homeMarkup, renderHome as renderHomeView } from './features/home/view.js';
import { catalogMarkup, renderCatalog as renderCatalogView } from './features/catalog/view.js';
import { programDetailMarkup, renderProgram as renderProgramView, renderProgramTab } from './features/program-detail/view.js';
import { comparisonMarkup, renderComparison } from './features/comparison/view.js';
import { setComparisonProgram } from './features/comparison/logic.js';
import { profileMarkup, renderProfile, renderProfileResults, renderProfileSummary, collectExamMetadata, collectExamScores, renderExamPicker, saveAndCalculateScores } from './features/profile/view.js';
import { shortlistMarkup, renderShortlist } from './features/shortlist/view.js';
import { moveShortlistItem, SHORTLIST_STATUSES, toggleShortlist } from './features/shortlist/logic.js';
import { interestTestMarkup, renderInterestTest } from './features/interest-test/view.js';
import { recordInterestAnswer, restartInterestTest, toggleInterestAnswer } from './features/interest-test/logic.js';
import { recommendationsMarkup, renderRecommendations } from './features/recommendations/view.js';
import { rulesMarkup, renderRulesPage } from './features/rules/view.js';
import { newsMarkup, renderNewsPage } from './features/news/view.js';
import { olympiadsMarkup, renderOlympiads } from './features/olympiads/view.js';
import { personalRouteMarkup, renderPersonalRoute } from './features/personal-route/view.js';
import { getProfileScoreTotal } from './data/exam-subjects.js';
import { admissionCheckMarkup, collectAdmissionScenario, evaluateAdmissionWithBackend, refreshAdmissionEstimate, renderAdmissionCheck } from './features/admission-check/view.js';
import { backendApi, isBackendConfigured } from './api/client.js';
import { escapeHtml } from './shared/dom.js';

const logger = createLogger('app');
const getProgram = getProgramById;
const toast = showToast;
const comparisonScope = { value: 'all' };
const comparisonCriterion = { value: 'admission' };
const comparisonCategory = { value: null };
let examPickerMode = { currentSubjectId: null };
const catalogFilters = { q: '', area: '', university: '', exam: '', budget: '', maxCost: '', format: '', duration: '', minScore: '', benefits: '', vuc: '' };
const appShell = document.querySelector('.app');
const sidebar = document.getElementById('app-sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');
const sidebarClose = document.getElementById('sidebar-close');
const menuBackdrop = document.getElementById('menu-backdrop');
const mainContent = document.querySelector('.main');

function syncSidebarToggle() {
  if (!appShell || !sidebarToggle) return;
  const isOpen = appShell.classList.contains('sidebar-open');
  const action = isOpen ? 'Закрыть' : 'Открыть';
  sidebarToggle.setAttribute('aria-expanded', String(isOpen));
  sidebarToggle.setAttribute('aria-label', `${action} меню навигации`);
  sidebarToggle.title = `${action} меню`;
  sidebarToggle.tabIndex = isOpen ? -1 : 0;
}

function setSidebarModalState(isOpen) {
  mainContent?.toggleAttribute('inert', isOpen);
  menuBackdrop?.setAttribute('aria-hidden', String(!isOpen));
  if (isOpen) {
    sidebar?.setAttribute('role', 'dialog');
    sidebar?.setAttribute('aria-modal', 'true');
  } else {
    sidebar?.removeAttribute('role');
    sidebar?.removeAttribute('aria-modal');
  }
}

function closeNavigationMenu({ restoreFocus = false } = {}) {
  if (!appShell?.classList.contains('sidebar-open')) return;
  appShell.classList.remove('sidebar-open');
  document.body.classList.remove('sidebar-locked');
  setSidebarModalState(false);
  syncSidebarToggle();
  if (restoreFocus) sidebarToggle?.focus();
}

syncSidebarToggle();

const featureMarkup = {
  home: homeMarkup,
  catalog: catalogMarkup,
  'program-detail': programDetailMarkup,
  'admission-check': admissionCheckMarkup,
  compare: comparisonMarkup,
  profile: profileMarkup,
  shortlist: shortlistMarkup,
  proftest: interestTestMarkup,
  recommendations: recommendationsMarkup,
  rules: rulesMarkup,
  news: newsMarkup,
  olympiads: olympiadsMarkup,
  'personal-route': personalRouteMarkup,
};

for (const [feature, markup] of Object.entries(featureMarkup)) {
  const mount = document.querySelector(`[data-page-mount="${feature}"]`);
  if (!mount) throw new Error(`Missing page mount: ${feature}`);
  mount.outerHTML = markup;
}

mountHugeicons();

const catalogFilterPanel = document.getElementById('catalog-filter-panel');
const catalogFilterTrigger = document.getElementById('catalog-filter-trigger');

function syncCatalogFilterForm() {
  const searchInput = document.getElementById('catalog-search');
  if (searchInput.value !== catalogFilters.q) searchInput.value = catalogFilters.q;
  document.getElementById('area-filter').value = catalogFilters.area;
  document.getElementById('university-filter').value = catalogFilters.university;
  document.getElementById('exam-filter').value = catalogFilters.exam;
  document.getElementById('max-cost-filter').value = catalogFilters.maxCost;
  document.getElementById('budget-filter').value = catalogFilters.budget;
  document.getElementById('format-filter').value = catalogFilters.format;
  document.getElementById('duration-filter').value = catalogFilters.duration;
  document.getElementById('min-score-filter').value = catalogFilters.minScore;
  document.getElementById('benefits-filter').value = catalogFilters.benefits;
  document.getElementById('vuc-filter').value = catalogFilters.vuc;
}

function setCatalogFilterPanelOpen(isOpen, { restoreAppliedFilters = false } = {}) {
  catalogFilterPanel?.classList.toggle('is-open', isOpen);
  catalogFilterPanel?.setAttribute('aria-hidden', String(!isOpen));
  catalogFilterPanel?.toggleAttribute('inert', !isOpen);
  catalogFilterTrigger?.setAttribute('aria-expanded', String(isOpen));
  if (!isOpen && restoreAppliedFilters) syncCatalogFilterForm();
}

catalogFilterTrigger?.setAttribute('aria-expanded', 'false');
catalogFilterPanel?.setAttribute('aria-hidden', 'true');
catalogFilterPanel?.setAttribute('inert', '');

const renderCard = (program, showActions = true) => renderProgramCard(program, {
  saved: Boolean(state.shortlist[program.id]),
  compared: state.comparison.includes(program.id),
  showActions,
});

const renderHome = () => loadRemotePrograms().then(() => renderHomeView({
  root: document, repository: catalogRepository, renderProgramCard: renderCard, state,
})).catch((error) => {
  logger.warn('home.catalog_backend_load_failed', { code: error.code });
  return renderHomeView({ root: document, repository: { getRecommendations: () => Promise.reject(error) }, renderProgramCard: renderCard, state });
});

const renderCatalog = ({ syncControls = true } = {}) => renderCatalogView({
  root: document,
  repository: catalogRepository,
  renderProgramCard: renderCard,
  filters: catalogFilters,
  profile: { ...state.profileInfo, scores: state.scores, examStatuses: state.examStatuses, interests: state.interests, preferences: state.preferences },
  syncControls,
});

let remoteProgramsLoadPromise = null;
function loadRemotePrograms() {
  if (!isBackendConfigured) return Promise.resolve(getAvailablePrograms());
  if (!remoteProgramsLoadPromise) remoteProgramsLoadPromise = backendApi.listPrograms({ limit: 100 })
    .then((payload) => {
      cacheRemotePrograms(payload?.items || payload || [], { replace: true, complete: true });
      const known = new Set(getAvailablePrograms().map((program) => String(program.id)));
      updateState('catalog.remove-unavailable-programs', (current) => {
        current.shortlist = Object.fromEntries(Object.entries(current.shortlist).filter(([id]) => known.has(id)));
        current.comparison = current.comparison.filter((id) => known.has(id));
        current.viewed = current.viewed.filter((id) => known.has(id));
      });
      return getAvailablePrograms();
    })
    .catch((error) => {
      remoteProgramsLoadPromise = null;
      throw error;
    });
  return remoteProgramsLoadPromise;
}

const examSubjectLabel = (exam) => {
  const subject = exam?.subject;
  if (typeof subject === 'string') return subject;
  if (subject && typeof subject === 'object') return subject.name || subject.label || subject.title || '';
  return exam?.subjectName || exam?.subjectLabel || exam?.sourceName || exam?.name || exam?.subjectId || '';
};

const currentAdmissionSubjects = (admissions) => {
  const offers = [...(admissions?.offerings || [])].sort((a, b) => Number(b.admissionYear || 0) - Number(a.admissionYear || 0));
  const year = offers[0]?.admissionYear;
  const currentOffers = offers.filter((offer) => offer.admissionYear === year && Array.isArray(offer.exams) && offer.exams.length);
  const exams = currentOffers[0]?.exams || [];
  const labels = exams.map((exam) => `${examSubjectLabel(exam)}${exam.isChoice ? ' (на выбор)' : ''}`).filter(Boolean);
  return [...new Set(labels)].join(' · ');
};

const renderProgram = (id) => {
  if (!id) {
    const host = document.getElementById('program-detail');
    if (host) host.innerHTML = '<div class="panel empty"><strong>Каталог пока недоступен</strong>Загрузите реальные записи API, затем откройте программу из каталога.</div>';
    return;
  }
  const render = () => renderProgramView(id, { root: document, state, updateState, getProgram, programs: getAvailablePrograms() });
  render();
  if (isBackendConfigured) Promise.all([
    backendApi.getProgram(id),
    backendApi.getCurriculum(id).catch(() => null),
    backendApi.getAdmissions(id).catch(() => null),
  ]).then(([record, curriculum, admissions]) => {
    const base = record?.program || record;
    if (!base?.id) return;
    const items = (curriculum?.items || []).map((item) => [item.discipline?.name || item.sourceName || '', item.discipline?.areaWeights?.find((area) => area.code === item.discipline.primaryArea)?.name || item.discipline?.primaryArea || '', item.semester ?? null, item.hours ?? 0, (item.assessmentTypes || []).join(', '), true]);
    const offers = (admissions?.offerings || []).slice().sort((a, b) => b.admissionYear - a.admissionYear);
    const offer = offers[0];
    const passing = offer?.passingScores?.find((item) => item.status === 'numeric' && item.score)?.score;
    const tuition = offer?.tuition?.find((item) => item.amount != null);
    const source = base.provenance?.find((item) => item.sourceUrl || item.url);
    const enriched = {
      ...base,
      curriculum: items,
      exams: currentAdmissionSubjects(admissions) || base.exams,
      passing: passing ?? base.passing,
      budget: offer?.places ?? base.budget,
      cost: tuition?.amount ?? base.cost,
      provenance: source ? [{ ...source, sourceUrl: source.sourceUrl || source.url, sourceTitle: source.sourceName }] : base.provenance,
      curriculumSource: curriculum?.sourceUrl,
      curriculumCheckedAt: curriculum?.capturedAt,
      curriculumSourceGaps: curriculum?.sourceGaps || [],
    };
    cacheRemotePrograms([enriched]);
    render();
  }).catch((error) => logger.warn('program.backend_load_failed', { programId: id, code: error.code }));
};

const comparisonCurriculumLoads = new Map();
const comparisonAdmissionLoads = new Map();
const renderCompare = () => {
  const render = () => renderComparison({ root: document, programs: getAvailablePrograms(), state, getProgram, formatMoney, scope: comparisonScope, criterion: comparisonCriterion, selectedCategory: comparisonCategory });
  render();
  if (!isBackendConfigured) return;
  loadRemotePrograms().then(async (items) => {
    const ids = state.comparison.slice(0, 4).filter((id) => items.some((program) => program.id === id));
    await Promise.all(ids.map((id) => {
      const loads = [];
      if (!comparisonCurriculumLoads.has(id)) {
        comparisonCurriculumLoads.set(id, backendApi.getCurriculum(id).then((payload) => {
          const base = getProgram(id);
          const curriculum = (payload?.items || []).map((item) => [item.discipline?.name || item.sourceName || '', item.discipline?.areaWeights?.find((area) => area.code === item.discipline.primaryArea)?.name || item.discipline?.primaryArea || '', item.semester ?? null, item.hours ?? 0, (item.assessmentTypes || []).join(', '), true]);
          if (base) cacheRemotePrograms([{ ...base, curriculum, curriculumSource: payload?.sourceUrl, curriculumCheckedAt: payload?.capturedAt }]);
        }).catch((error) => logger.warn('comparison.curriculum_backend_load_failed', { programId: id, code: error.code })));
      }
      loads.push(comparisonCurriculumLoads.get(id));
      if (!comparisonAdmissionLoads.has(id)) {
        comparisonAdmissionLoads.set(id, backendApi.getAdmissions(id).then((payload) => {
          const base = getProgram(id);
          const exams = currentAdmissionSubjects(payload);
          if (base && exams) cacheRemotePrograms([{ ...base, exams }]);
        }).catch((error) => logger.warn('comparison.admissions_backend_load_failed', { programId: id, code: error.code })));
      }
      loads.push(comparisonAdmissionLoads.get(id));
      return Promise.all(loads);
    }));
    render();
  }).catch((error) => logger.warn('comparison.programs_backend_load_failed', { code: error.code }));
};

let profileFetchAttempted = false;
let profileProgramsLoadStarted = false;
const renderProfilePage = () => {
  renderProfile({ root: document, state, programs: getAvailablePrograms() });
  if (isBackendConfigured && !profileProgramsLoadStarted) {
    profileProgramsLoadStarted = true;
    loadRemotePrograms().then((items) => renderProfile({ root: document, state, programs: items }))
      .catch((error) => { profileProgramsLoadStarted = false; logger.warn('profile.programs_backend_load_failed', { code: error.code }); });
  }
  if (!isBackendConfigured || profileFetchAttempted) return;
  profileFetchAttempted = true;
  const hasLocalProfile = Boolean(state.profileInfo.name || Object.keys(state.scores).length || Object.keys(state.interests).length || Object.values(state.preferences || {}).some(Boolean) || state.maxNotifications.enabled);
  if (hasLocalProfile) { syncProfileToBackend(); return; }
  backendApi.getProfile(state.activeExamProfileId).then((payload) => {
    const remote = payload?.profile || payload;
    if (!remote || typeof remote !== 'object') return;
    updateState('profile.backend.restore', (current) => {
      current.profileInfo = {
        name: typeof remote.name === 'string' ? remote.name : current.profileInfo.name,
        admissionYear: Number(remote.admissionYear) || current.profileInfo.admissionYear,
      };
      if (Array.isArray(remote.exams)) {
        current.scores = Object.fromEntries(remote.exams.map((item) => [
          item.subjectId,
          item.status === 'taken' && item.score !== null && item.score !== undefined && item.score !== '' && Number.isFinite(Number(item.score)) ? Number(item.score) : null,
        ]));
        if (remote.extraPoints !== null && remote.extraPoints !== undefined) current.scores.extra = Number(remote.extraPoints) || 0;
        current.examStatuses = Object.fromEntries(remote.exams.map((item) => [item.subjectId, item.status]));
        current.examRanges = Object.fromEntries(remote.exams.filter((item) => item.status === 'range').map((item) => [item.subjectId, { min: item.minScore, max: item.maxScore }]));
        const active = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
        if (active) Object.assign(active, { scores: { ...current.scores }, examStatuses: { ...current.examStatuses }, examRanges: { ...current.examRanges } });
      }
      if (remote.interests && typeof remote.interests === 'object') current.interests = remote.interests;
      if (remote.preferences && typeof remote.preferences === 'object') current.preferences = { ...current.preferences, ...remote.preferences };
      if (remote.maxNotifications && typeof remote.maxNotifications === 'object') current.maxNotifications = { ...current.maxNotifications, ...remote.maxNotifications };
    });
    renderProfile({ root: document, state, programs: getAvailablePrograms() });
  }).catch((error) => logger.warn('profile.backend_load_failed', { code: error.code, status: error.status }));
};
const renderShortlistPage = () => renderShortlist({ root: document, state, getProgram });
function renderInterestTestView() {
  return renderInterestTest({ root: document, state, questions: interestQuestions, updateState });
}

const renderRecommendationList = () => {
  if (!isBackendConfigured) return renderRecommendations({ root: document, programs: getAvailablePrograms(), state });
  loadRemotePrograms().then((items) => renderRecommendations({ root: document, programs: items, state }))
    .catch((error) => { logger.warn('recommendations.programs_backend_load_failed', { code: error.code }); document.getElementById('recommendations-list').innerHTML = '<div class="empty"><strong>Каталог API временно недоступен</strong>Попробуйте открыть раздел позже.</div>'; });
};
const renderPersonalRoutePage = () => renderPersonalRoute({ root: document, state, questions: interestQuestions });
let activeAdmissionPrograms = programs;
const renderAdmissionPage = () => {
  const render = (items) => {
    activeAdmissionPrograms = items;
    renderAdmissionCheck({ root: document, programs: items, state });
  };
  render(getAvailablePrograms());
  if (isBackendConfigured) loadRemotePrograms().then(async (items) => {
    const withAdmissions = await Promise.all(items.map(async (program) => {
      try {
        const payload = await backendApi.getAdmissions(program.id);
        const offerings = (payload?.offerings || []).slice().sort((a, b) => b.admissionYear - a.admissionYear);
        const offering = offerings.find((item) => item.admissionYear === Number(state.profileInfo.admissionYear)) || offerings[0];
        return { ...program, exams: (offering?.exams || []).map((exam) => exam.subject || exam.sourceName || exam.subjectId || exam.name).filter(Boolean).join(' · '), examRequirements: offering?.exams || [], admissionYear: offering?.admissionYear };
      } catch { return program; }
    }));
    cacheRemotePrograms(withAdmissions);
    render(withAdmissions);
  }).catch((error) => logger.warn('admission.programs_backend_load_failed', { code: error.code }));
};

async function syncProfileToBackend() {
  // The Public API v1 profile contract stores ProfTest signals, not EGE scores.
  // Applicant-entered scores stay in the user's browser until a matching contract exists.
}

const { openPage } = createNavigator({
  home: renderHome,
  catalog: renderCatalog,
  compare: renderCompare,
  shortlist: renderShortlistPage,
  program: ({ id }) => renderProgram(id || getAvailablePrograms()[0]?.id),
  'admission-check': renderAdmissionPage,
  profile: renderProfilePage,
  proftest: renderInterestTestView,
  recommendations: renderRecommendationList,
  rules: () => loadRemotePrograms().then((items) => renderRulesPage({ root: document, programs: items })).catch(() => renderRulesPage({ root: document, programs: getAvailablePrograms() })),
  news: () => renderNewsPage({ root: document }),
  olympiads: () => renderOlympiads({ root: document }),
  'personal-route': renderPersonalRoutePage,
});

function rerenderActivePage(page, programId) {
  const renderers = {
    catalog: renderCatalog,
    program: () => renderProgram(programId || state.viewed.at(-1) || getAvailablePrograms()[0]?.id),
    profile: () => {
      const total = getProfileScoreTotal(state.scores);
      renderProfileResults({ root: document, state, programs: getAvailablePrograms(), total });
    },
    shortlist: renderShortlistPage,
    recommendations: renderRecommendationList,
  };
  renderers[page]?.();
}

function handleClick(event) {
  if (appShell?.classList.contains('sidebar-open')
    && !event.target.closest('.sidebar, #sidebar-toggle')) closeNavigationMenu({ restoreFocus: true });
  if (handleAssistantClick(event)) return;
  if (event.target.matches?.('#ege-subject-picker')) {
    event.target.close();
    return;
  }
  const target = event.target.closest('button, a, [data-page], [data-save], [data-answer], [data-category-select], [data-category-reset]');
  if (!target) return;

  if (target.matches('[data-category-select]')) {
    const nextCategory = target.dataset.categorySelect;
    comparisonCategory.value = comparisonCategory.value === nextCategory ? null : nextCategory;
    renderCompare();
    return;
  }

  if (target.matches('[data-category-reset]')) {
    comparisonCategory.value = null;
    renderCompare();
    return;
  }

  if (target.id === 'olympiad-filters-reset') {
    document.getElementById('olympiad-search').value = '';
    document.getElementById('olympiad-subject-filter').value = '';
    document.getElementById('olympiad-level-filter').value = '';
    renderOlympiads({ root: document });
    document.getElementById('olympiad-search').focus();
    return;
  }

  if (target.matches('#sidebar-toggle')) {
    const opening = !appShell.classList.contains('sidebar-open');
    appShell.classList.toggle('sidebar-open', opening);
    document.body.classList.toggle('sidebar-locked', opening);
    setSidebarModalState(opening);
    if (opening) requestAnimationFrame(() => sidebarClose?.focus());
    syncSidebarToggle();
    return;
  }

  if (target.matches('#sidebar-close')) {
    closeNavigationMenu({ restoreFocus: true });
    return;
  }

  if (target.matches('#catalog-filter-trigger')) {
    const isOpen = catalogFilterPanel.classList.contains('is-open');
    setCatalogFilterPanelOpen(!isOpen, { restoreAppliedFilters: isOpen });
    return;
  }

  if (target.matches('#reset-filter')) {
    document.getElementById('catalog-filter-form').reset();
    Object.keys(catalogFilters).forEach((key) => { catalogFilters[key] = ''; });
    renderCatalog();
    return;
  }

  if (target.matches('[data-compare-print]')) {
    globalThis.print();
    return;
  }

  if (target.matches('[data-compare-share]')) {
    const url = new URL(globalThis.location.href);
    url.search = new URLSearchParams({ page: 'compare', programs: state.comparison.join(',') }).toString();
    if (!navigator.clipboard?.writeText) {
      toast(`Ссылка для копирования: ${url.href}`);
      return;
    }
    navigator.clipboard.writeText(url.href)
      .then(() => toast('Ссылка на сравнение скопирована'))
      .catch(() => toast(`Ссылка для копирования: ${url.href}`));
    return;
  }

  if (target.matches('[data-nav-toggle]')) {
    const section = target.closest('.nav-section');
    const shouldOpen = !section.hasAttribute('data-open');
    section.toggleAttribute('data-open', shouldOpen);
    target.setAttribute('aria-expanded', String(shouldOpen));
    section.querySelectorAll('.nav-leaf').forEach((button) => {
      button.tabIndex = shouldOpen ? 0 : -1;
    });
    return;
  }

  if (target.dataset.page) {
    event.preventDefault();
    closeNavigationMenu({ restoreFocus: true });
    openPage(target.dataset.page, { id: target.dataset.program });
    return;
  }

  if (target.matches('[data-tab]')) {
    document.querySelectorAll('[data-tab]').forEach((button) => {
      button.classList.toggle('active', button === target);
    });
    const detailButton = document.getElementById('detail-ask');
    const program = getProgram(detailButton?.dataset.programId) || getAvailablePrograms()[0];
    if (target.dataset.tab === 'overview') renderProgram(program.id);
    else renderProgramTab(program, target.dataset.tab, { root: document, formatMoney, state });
    return;
  }

  if (target.matches('[data-semester]')) {
    comparisonScope.value = target.dataset.semester === 'all' ? 'all' : Number(target.dataset.semester);
    renderCompare();
    return;
  }

  if (target.matches('[data-compare-criterion]')) {
    comparisonCriterion.value = target.dataset.compareCriterion;
    renderCompare();
    return;
  }

  if (target.matches('#admission-reset-scenario')) {
    renderAdmissionPage();
    return;
  }

  if (target.matches('#admission-check-rules')) {
    if (!isBackendConfigured) {
      toast('Настройте VITE_API_BASE_URL, чтобы отправить сценарий в backend.');
      return;
    }
    target.disabled = true;
    target.textContent = 'Проверяем правила…';
    evaluateAdmissionWithBackend({ root: document, programs: activeAdmissionPrograms, state })
      .then(() => toast('Получен ответ Andromeda API по введённым баллам'))
      .catch((error) => { logger.warn('admission.backend_evaluation_failed', { code: error.code, status: error.status }); toast('Andromeda API не вернуло проверку. Проверьте подключение и источники данных.'); })
      .finally(() => { target.disabled = false; target.textContent = 'Сверить баллы через API'; });
    return;
  }

  if (target.matches('[data-save]')) {
    const programId = target.dataset.save;
    const result = toggleShortlist({ programId, state, updateState });
    toast(result === 'removed' ? 'Программа убрана из shortlist' : 'Программа добавлена в «Пока рассматриваю»');
    rerenderActivePage(document.querySelector('.page.active')?.id.replace('page-', ''), programId);
    return;
  }

  if (target.matches('[data-shortlist-move]')) {
    const programId = target.dataset.programId;
    const currentIndex = SHORTLIST_STATUSES.findIndex(({ value }) => value === state.shortlist[programId]);
    if (currentIndex < 0) return;
    const direction = target.dataset.shortlistMove === 'up' ? -1 : 1;
    const nextStatus = SHORTLIST_STATUSES[currentIndex + direction];
    if (!nextStatus) return;

    moveShortlistItem({ programId, status: nextStatus.value, updateState });
    renderShortlistPage();
    toast(`Перемещено: ${nextStatus.label}`);
    return;
  }

  if (target.matches('[data-compare-toggle]')) {
    const programId = target.dataset.compareToggle;
    const isSelected = state.comparison.includes(programId);
    const result = setComparisonProgram({
      programId,
      selected: !isSelected,
      state,
      updateState,
    });

    if (result === 'limit') return toast('Можно сравнить максимум 4 программы');

    const selected = result === 'added';
    target.setAttribute('aria-pressed', String(selected));
    target.setAttribute('aria-label', selected ? 'Убрать из сравнения' : 'Добавить в сравнение');
    target.title = selected ? 'Убрать из сравнения' : 'Добавить в сравнение';
    target.classList.toggle('btn-primary', !selected);
    target.classList.toggle('btn-outline', selected);
    target.textContent = target.closest('.program-card')
      ? (selected ? 'Убрать' : 'Сравнить')
      : (selected ? 'Убрать из сравнения' : '⇄ Сравнить');
    toast(selected ? 'Программа добавлена в сравнение' : 'Программа убрана из сравнения');
    return;
  }

  if (target.matches('[data-answer]')) {
    toggleInterestAnswer({ answer: Number(target.dataset.answer), state, updateState });
    renderInterestTestView();
    return;
  }

  if (target.matches('#test-next, #test-skip, #test-finish')) {
    recordInterestAnswer({
      state,
      updateState,
      skip: target.id === 'test-skip',
      finish: target.id === 'test-finish',
    });
    renderInterestTestView();
    return;
  }

  if (target.id === 'test-restart') {
    restartInterestTest({ updateState });
    renderInterestTestView();
    return;
  }

  if (target.id === 'detail-next') {
    openPage('profile');
    return;
  }

  if (target.id === 'add-exam-profile') {
    const form = document.getElementById('exam-profile-create');
    form.hidden = !form.hidden;
    target.setAttribute('aria-expanded', String(!form.hidden));
    if (!form.hidden) {
      document.getElementById('new-profile-year').value = state.profileInfo.admissionYear;
      document.getElementById('new-profile-name').focus();
    }
    return;
  }

  if (target.id === 'cancel-exam-profile') {
    const form = document.getElementById('exam-profile-create');
    form.reset();
    form.hidden = true;
    document.getElementById('add-exam-profile').setAttribute('aria-expanded', 'false');
    document.getElementById('add-exam-profile').focus();
    return;
  }

  if (target.id === 'add-ege-subject') {
    examPickerMode = { currentSubjectId: null };
    const search = document.getElementById('ege-subject-search');
    search.value = '';
    renderExamPicker({ root: document, scores: state.scores });
    document.getElementById('ege-subject-picker').showModal();
    search.focus();
    return;
  }

  if (target.matches('[data-edit-ege-subject]')) {
    examPickerMode = { currentSubjectId: target.closest('[data-exam-row]')?.dataset.subjectId || null };
    const search = document.getElementById('ege-subject-search');
    search.value = '';
    renderExamPicker({ root: document, scores: state.scores, currentSubjectId: examPickerMode.currentSubjectId });
    document.getElementById('ege-subject-picker').showModal();
    search.focus();
    return;
  }

  if (target.id === 'close-ege-picker') {
    document.getElementById('ege-subject-picker').close();
    return;
  }

  if (target.matches('[data-ege-subject-option]')) {
    const subjectId = target.dataset.egeSubjectOption;
    const scores = collectExamScores(document);
    const oldSubjectId = examPickerMode.currentSubjectId;
    const previousStatus = oldSubjectId ? state.examStatuses?.[oldSubjectId] : null;
    const previousRange = oldSubjectId ? state.examRanges?.[oldSubjectId] : null;
    if (examPickerMode.currentSubjectId) {
      const previousScore = scores[examPickerMode.currentSubjectId];
      delete scores[examPickerMode.currentSubjectId];
      scores[subjectId] = previousScore ?? null;
    } else {
      scores[subjectId] = null;
    }
    document.getElementById('ege-subject-picker').close();
    updateState('profile.exam.subject.select', (current) => {
      current.scores = scores;
      if (oldSubjectId) {
        delete current.examStatuses[oldSubjectId];
        delete current.examRanges[oldSubjectId];
        current.examStatuses[subjectId] = previousStatus || (scores[subjectId] != null ? 'taken' : 'not-taken');
        if (previousRange) current.examRanges[subjectId] = previousRange;
      } else current.examStatuses[subjectId] = 'not-taken';
      const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
      if (activeProfile) {
        activeProfile.scores = { ...scores };
        activeProfile.examStatuses = { ...current.examStatuses };
        activeProfile.examRanges = { ...current.examRanges };
      }
    });
    renderProfilePage();
    document.querySelector(`[data-subject-id="${subjectId}"] [data-exam-score]`)?.focus();
    toast(examPickerMode.currentSubjectId ? 'Предмет заменён, баллы сохранены' : 'Предмет добавлен');
    examPickerMode = { currentSubjectId: null };
    return;
  }

  if (target.matches('[data-exam-remove]')) {
    target.closest('[data-exam-row]')?.remove();
    const scores = collectExamScores(document);
    updateState('profile.exam.remove', (current) => {
      current.scores = scores;
      const metadata = collectExamMetadata(document);
      current.examStatuses = metadata.examStatuses;
      current.examRanges = metadata.examRanges;
      const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
      if (activeProfile) Object.assign(activeProfile, { scores: { ...scores }, ...metadata });
    });
    renderProfilePage();
    document.getElementById('add-ege-subject').focus();
    return;
  }

  if (target.matches('[data-exam-profile]')) {
    const profileId = target.dataset.examProfile;
    const profile = state.examProfiles.find((item) => item.id === profileId);
    if (!profile || profileId === state.activeExamProfileId) return;

    const savedTotal = saveAndCalculateScores({ root: document, state, updateState, programs: getAvailablePrograms() });
    if (savedTotal === null) return;
    updateState('exam-profile.select', (current) => {
      current.activeExamProfileId = profileId;
      current.scores = { ...profile.scores };
      current.examStatuses = { ...(profile.examStatuses || {}) };
      current.examRanges = { ...(profile.examRanges || {}) };
    });
    renderProfilePage();
    return;
  }

  if (target.id === 'calculate-btn') {
    const savedTotal = saveAndCalculateScores({ root: document, state, updateState, programs: getAvailablePrograms() });
    if (savedTotal !== null) { syncProfileToBackend(); toast('Профиль ЕГЭ сохранён, результаты обновлены'); }
    return;
  }

  if (target.matches('.plan-toggle button')) {
    const panel = target.closest('.curriculum-compare');
    const grid = panel?.querySelector('.plan-grid');
    const showSubjects = target.textContent.includes('Предметы');
    grid?.classList.toggle('subjects-only', showSubjects);
    grid?.classList.toggle('hours-only', !showSubjects);
    panel?.querySelectorAll('.plan-toggle button').forEach((button) => {
      button.classList.toggle('active', button === target);
    });
    return;
  }

  if (target.matches('.compare-toggle')) target.classList.toggle('active');

  if (target.matches('#admission-save-profile')) {
    const scenario = collectAdmissionScenario(document);
    updateState('admission-check.save-profile', (current) => {
      current.scores = { ...current.scores, ...scenario.scores };
      current.examStatuses = { ...current.examStatuses, ...scenario.examStatuses };
      for (const subjectId of Object.keys(scenario.examStatuses)) delete current.examRanges[subjectId];
      current.examRanges = { ...current.examRanges, ...scenario.examRanges };
      const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
      if (activeProfile) Object.assign(activeProfile, { scores: { ...current.scores }, examStatuses: { ...current.examStatuses }, examRanges: { ...current.examRanges } });
    });
    syncProfileToBackend();
    toast('Статусы и баллы сохранены в профиль ЕГЭ');
    return;
  }
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && catalogFilterPanel?.classList.contains('is-open')) {
    setCatalogFilterPanelOpen(false, { restoreAppliedFilters: true });
    catalogFilterTrigger?.focus();
    return;
  }

  if (!appShell?.classList.contains('sidebar-open')) return;
  if (event.key === 'Escape') {
    closeNavigationMenu({ restoreFocus: true });
    return;
  }
  if (event.key !== 'Tab') return;

  const focusable = [...document.querySelectorAll('#app-sidebar a[href], #app-sidebar button:not([disabled]), #app-sidebar [tabindex]:not([tabindex="-1"])')]
    .filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
  if (focusable.length === 0) {
    event.preventDefault();
    sidebarClose?.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && (document.activeElement === first || !appShell.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !appShell.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
});

function handleChange(event) {
  const { target } = event;
  if (target.matches('[data-admission-status]')) {
    const row = target.closest('[data-admission-subject]');
    const score = row?.querySelector('[data-admission-score]');
    const range = row?.querySelector('[data-admission-range-fields]');
    if (score) score.disabled = target.value !== 'taken';
    if (range) range.hidden = target.value !== 'range';
    refreshAdmissionEstimate({ root: document, programs: activeAdmissionPrograms, state });
    return;
  }
  if (target.matches('#scenario-bvi, #scenario-olympiad, #scenario-benefit, #scenario-paid')) {
    if (target.id === 'scenario-olympiad') document.querySelector('[data-scenario-olympiad-fields]').hidden = !target.checked;
    if (target.id === 'scenario-benefit') document.querySelector('[data-scenario-benefit-field]').hidden = !target.checked;
    refreshAdmissionEstimate({ root: document, programs: activeAdmissionPrograms, state });
    return;
  }
  if (target.matches('[data-test-note]')) {
    const step = state.testStep;
    updateState('interest-test.note.save', (current) => { current.testNotes[step] = target.value.trim().slice(0, 240); });
    return;
  }
  if (target.matches('[data-shortlist-note]')) {
    const programId = target.dataset.shortlistNote;
    updateState('shortlist.note.save', (current) => {
      current.shortlistNotes[programId] = target.value.trim().slice(0, 240);
    });
    return;
  }
  if (target.matches('#olympiad-subject-filter, #olympiad-level-filter')) {
    renderOlympiads({ root: document });
    return;
  }
  if (target.matches('[data-profile-info]')) {
    const field = target.dataset.profileInfo;
    const value = field === 'admissionYear' ? Number(target.value) : target.value.trim().slice(0, 80);
    if (field === 'admissionYear' && (!Number.isInteger(value) || value < 2024 || value > 2035)) {
      target.value = state.profileInfo.admissionYear;
      return;
    }

    updateState('profile.info.update', (current) => { current.profileInfo[field] = value; });
    if (field === 'name') {
      document.getElementById('profile-avatar').textContent = value.slice(0, 1).toLocaleUpperCase('ru-RU') || 'Я';
      document.getElementById('personal-profile-heading').textContent = value || 'Абитуриент';
    }
    syncProfileToBackend();
    return;
  }

  if (target.matches('[data-exam-score], [data-extra-points]')) {
    if (!target.checkValidity()) {
      const subjectId = target.matches('[data-exam-score]')
        ? target.closest('[data-exam-row]')?.dataset.subjectId
        : 'extra';
      const previousValue = state.scores[subjectId];
      target.value = previousValue ?? '';
      target.reportValidity();
      return;
    }

    const scores = collectExamScores(document);
    updateState('profile.score.edit', (current) => {
      current.scores = scores;
      const metadata = collectExamMetadata(document);
      current.examStatuses = metadata.examStatuses;
      current.examRanges = metadata.examRanges;
      const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
      if (activeProfile) Object.assign(activeProfile, { scores: { ...scores }, ...metadata });
    });
    renderProfileSummary({ root: document, state, programs: getAvailablePrograms() });
    syncProfileToBackend();
    return;
  }

  if (target.matches('[data-exam-status], [data-exam-range-min], [data-exam-range-max]')) {
    const scores = collectExamScores(document);
    const metadata = collectExamMetadata(document);
    updateState('profile.exam.status.update', (current) => {
      current.scores = scores;
      current.examStatuses = metadata.examStatuses;
      current.examRanges = metadata.examRanges;
      const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
      if (activeProfile) Object.assign(activeProfile, { scores: { ...scores }, ...metadata });
    });
    renderProfilePage();
    syncProfileToBackend();
    return;
  }

  if (target.matches('[data-preference]')) {
    const key = target.dataset.preference;
    const value = ['maxCost', 'durationYears'].includes(key) ? (target.value ? Number(target.value) : '') : target.value.trim().slice(0, key === 'degree' ? 80 : 120);
    updateState('profile.preference.update', (current) => { current.preferences[key] = value; });
    renderCatalog({ syncControls: false });
    syncProfileToBackend();
    return;
  }

  if (target.matches('[data-interest-preference]')) {
    updateState('profile.interest.preference', (current) => { current.interests[target.dataset.interestPreference] = target.checked ? Math.max(1, Number(current.interests[target.dataset.interestPreference]) || 0) : 0; });
    renderCatalog({ syncControls: false });
    syncProfileToBackend();
    return;
  }

  if (target.matches('[data-max-notification], [data-max-enabled]')) {
    updateState('profile.max.notifications', (current) => {
      if (target.matches('[data-max-enabled]')) current.maxNotifications.enabled = target.checked;
      else {
        const topic = target.dataset.maxNotification;
        current.maxNotifications.topics = target.checked
          ? [...new Set([...current.maxNotifications.topics, topic])]
          : current.maxNotifications.topics.filter((saved) => saved !== topic);
      }
    });
    return;
  }

  if (target.matches('[data-compare]')) {
    const programId = target.dataset.compare;
    const result = setComparisonProgram({ programId, selected: target.checked, state, updateState });
    if (result === 'limit') {
      target.checked = false;
      toast('Можно сравнить максимум 4 программы');
      return;
    }
    renderCompare();
    return;
  }

}

function handleSubmit(event) {
  const form = event.target;
  if (form.id === 'catalog-filter-form') {
    event.preventDefault();
    catalogFilters.area = document.getElementById('area-filter').value;
    catalogFilters.university = document.getElementById('university-filter').value;
    catalogFilters.exam = document.getElementById('exam-filter').value;
    catalogFilters.budget = document.getElementById('budget-filter').value;
    catalogFilters.maxCost = document.getElementById('max-cost-filter').value;
    catalogFilters.format = document.getElementById('format-filter').value;
    catalogFilters.duration = document.getElementById('duration-filter').value;
    catalogFilters.minScore = document.getElementById('min-score-filter').value;
    catalogFilters.benefits = document.getElementById('benefits-filter').value;
    catalogFilters.vuc = document.getElementById('vuc-filter').value;
    setCatalogFilterPanelOpen(false);
    catalogFilterTrigger.focus();
    renderCatalog();
    return;
  }

  if (form.id !== 'exam-profile-create') return;
  event.preventDefault();

  const formData = new FormData(form);
  const name = String(formData.get('profileName') || '').trim().slice(0, 80);
  const year = Number(formData.get('profileYear'));
  if (!name || !Number.isInteger(year) || year < 2024 || year > 2035) return;

  const id = `exam-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`}`;
  const savedTotal = saveAndCalculateScores({ root: document, state, updateState, programs: getAvailablePrograms() });
  if (savedTotal === null) return;
  updateState('exam-profile.create', (current) => {
    current.examProfiles.push({ id, name, year, scores: {}, examStatuses: {}, examRanges: {} });
    current.activeExamProfileId = id;
    current.scores = {};
    current.examStatuses = {};
    current.examRanges = {};
  });
  renderProfilePage();
  toast('Профиль ЕГЭ создан');
}

function handleInput(event) {
  if (event.target.matches('[data-admission-score], [data-admission-range-min], [data-admission-range-max]')) {
    if (event.target.value !== '' && !event.target.checkValidity()) {
      event.target.value = '';
      event.target.reportValidity();
    }
    refreshAdmissionEstimate({ root: document, programs: activeAdmissionPrograms, state });
    return;
  }

  if (event.target.matches('#scenario-olympiad-record, #scenario-olympiad-profile, #scenario-benefit-id')) {
    refreshAdmissionEstimate({ root: document, programs: activeAdmissionPrograms, state });
    return;
  }

  if (event.target.matches('#olympiad-search')) {
    renderOlympiads({ root: document });
    return;
  }

  if (event.target.matches('#catalog-search')) {
    catalogFilters.q = event.target.value;
    renderCatalog({ syncControls: false });
  }

  if (event.target.matches('#ege-subject-search')) {
    renderExamPicker({
      root: document,
      scores: state.scores,
      query: event.target.value,
      currentSubjectId: examPickerMode.currentSubjectId,
    });
  }
}

subscribeToState(() => updateShellStats(state));
document.addEventListener('click', handleClick);
document.addEventListener('change', handleChange);
document.addEventListener('input', handleInput);
document.addEventListener('submit', handleSubmit);
const startupQuery = new URLSearchParams(globalThis.location?.search || '');
const startupPage = startupQuery.get('page');
if (startupPage === 'compare') {
  const requestedIds = (startupQuery.get('programs') || '').split(',').filter((id) => getProgram(id)).slice(0, 4);
  if (requestedIds.length >= 2) updateState('comparison.deep-link.open', (current) => { current.comparison = requestedIds; });
}
if (startupPage && (featureMarkup[startupPage] || startupPage === 'program')) {
  openPage(startupPage, { id: startupQuery.get('program') || undefined });
} else {
  renderHome().catch((error) => logger.error('startup.render_failed', { errorName: error.name }));
}
updateShellStats(state);
logger.info('started', { pageCount: Object.keys(featureMarkup).length, programCount: programs.length });
