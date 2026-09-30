export const MAX_COMPARISON_PROGRAMS = 4;

export function setComparisonProgram({ programId, selected, state, updateState }) {
  const isSelected = state.comparison.includes(programId);
  if (isSelected === selected) return 'unchanged';
  if (selected && state.comparison.length >= MAX_COMPARISON_PROGRAMS) return 'limit';

  updateState(selected ? 'comparison.add' : 'comparison.remove', (current) => {
    if (selected) current.comparison.push(programId);
    else current.comparison = current.comparison.filter((id) => id !== programId);
  });

  return selected ? 'added' : 'removed';
}

export function selectComparisonPrograms(ids, getProgram) {
  return ids.map(getProgram).filter(Boolean);
}

export function hasMinimumComparisonPrograms(programs) {
  return programs.length >= 2;
}

export function normalizeComparisonScope(scope, programs) {
  const maxSemester = Math.max(1, ...programs.flatMap((program) => program.curriculum.map((row) => row[2])));
  return {
    maxSemester,
    scope: scope !== 'all' && scope > maxSemester ? 'all' : scope,
  };
}

export function calculatePlanStats(program, scope = 'all') {
  const subjects = scope === 'all'
    ? program.curriculum
    : program.curriculum.filter((row) => row[2] === scope);
  const byArea = {};

  for (const [, area, , hours] of subjects) {
    byArea[area] = (byArea[area] || 0) + hours;
  }

  return {
    byArea,
    total: Object.values(byArea).reduce((sum, hours) => sum + hours, 0),
    subjects,
  };
}
