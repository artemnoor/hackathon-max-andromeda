export function groupProgramsByScore(programs, total) {
  return [
    {
      name: 'Выше демонстрационного ориентира',
      className: 'good',
      programs: programs.filter((program) => total >= program.passing + 10),
    },
    {
      name: 'Рядом с демонстрационным ориентиром',
      className: 'borderline',
      programs: programs.filter((program) => total >= program.passing - 10 && total < program.passing + 10),
    },
    {
      name: 'Ниже демонстрационного ориентира',
      className: 'low',
      programs: programs.filter((program) => total < program.passing - 10),
    },
  ];
}
