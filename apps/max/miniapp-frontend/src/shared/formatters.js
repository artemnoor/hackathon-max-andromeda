const currencyFormatter = new Intl.NumberFormat('ru-RU');

export function formatMoney(amount) {
  if (amount === null || amount === undefined || amount === '') return 'Нет данных';
  return `${currencyFormatter.format(amount)} ₽`;
}
