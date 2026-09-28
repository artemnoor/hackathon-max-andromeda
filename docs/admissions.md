[← API](api.md) · [Back to README](../README.md) · [Admission Fit →](admission-fit.md)

# Admissions

Admissions — read-only vertical slice с source-backed условиями поступления по canonical `program_id`. Он не вычисляет `Admission Fit`, вероятность поступления или рейтинг программ.

## Data flow

```text
BMSTU detail API + official orders manifest/PDFs
  → raw admission DTOs with source hashes
  → BMSTU normalization + canonical program identity
  → admission_offerings + route-aware passing-score children
  → AdmissionReader → AdmissionService
  → GET /programs/{id}/admissions → program UI
```

`admissions` не импортирует ORM, SQLAlchemy или parser internals. Service получает программу через публичный `ProgramReader`, а данные поступления — через `AdmissionReader`. У каждой offering и каждого дочернего показателя хранится provenance: source kind, URL, capture timestamp, content hash и locator.

An offering may carry a source-backed campus and exam choice-group cardinalities. Missing source values remain unknown. Admission-benefit evaluation selects exactly one matching offering; competitive-score calculation counts required exams and only the source-defined number of alternatives in each choice group, never every score supplied by the applicant.

## Source hierarchy and score semantics

Парсер использует только официальные публичные источники МГТУ:

- [каталог и detail API](https://bmstu.ru/bachelor/majors) дают направления, профили, места, стоимость и `points[]` — предметные минимумы допуска;
- [manifest приказов](https://priem.bmstu.ru/lists/orders.json) обнаруживается динамически, а каждый его `href` ведёт на официальный PDF списка зачисленных;
- [статистика прошлых лет](https://kf.bmstu.ru/bakalavriat-i-specialitet/statistika-proshlykh-let) используется только как пояснение определения исторического проходного балла.

Для одного `(admission_year, study_form, funding_type, competition_type)` числовой `score` — это `min(Сумма баллов)` среди опубликованных зачисленных строк. В сумму входят вступительные испытания (`ВИ`) и индивидуальные достижения (`ИД`); parser никогда не подставляет вместо неё компонент или `points[].point`. Это наблюдение по кампании, а не гарантия будущего зачисления.

## Route/status contract

| `competition_type` | `status` | Значение |
|---|---|---|
| `general` | `numeric` | общий конкурс, числовой минимум зачисленных |
| `special_quota` | `numeric` | минимум по особой квоте |
| `separate_quota` | `numeric` | минимум по отдельной квоте |
| `targeted` | `numeric` | минимум по целевой квоте; `funding_type` остаётся бюджетным |
| `bvi` | `bvi` | зачисление без вступительных испытаний; `score` всегда `null` |
| quota route + `bvi` | `bvi` | смешанный раздел: numeric minimum и отдельный BVI факт |
| `other` | `numeric` | опубликованный, но не распознанный специальный маршрут |

Отсутствие направления или категории в официальном PDF — это `source_gap`, а не `score=0`. Ошибка извлечения PDF, неизвестный заголовок, недоступный study plan и неподдерживаемый уровень образования фиксируются раздельно. Master/postgraduate order PDFs захватываются и классифицируются, но текущий canonical catalog поддерживает только bachelor/specialist, поэтому такие документы не проецируются в программы.

`Admission Fit` использует только `status=numeric` и `competition_type=general`; quota/BVI facts видны в admissions, но не превращаются в обычный порог готовности.

## Source inventory and gaps

| Поле | Доступный источник в текущем fixture | Поведение |
|---|---|---|
| год набора | BMSTU detail `additional`/current payload | сохраняется как offering year |
| форма обучения | BMSTU detail `price` | нормализуется в `StudyForm` |
| бюджет/платное | BMSTU detail `places` и `price` | отдельные offerings |
| бюджетные и платные места | BMSTU detail `places` | `places` nullable, без догадок |
| ЕГЭ и минимумы | BMSTU detail `points` | отдельные typed exam requirements |
| стоимость | BMSTU detail `price` | отдельные regular/discounted tuition rows |
| исторические проходные | BMSTU detail `additional.oldPoints` | отдельные historical offerings |
| квоты | текущий fixture detail не публикует квоты | пустая коллекция; `0` не подставляется |
| списки зачисленных и observed minima | официальный [orders manifest](https://priem.bmstu.ru/lists/orders.json) и его PDF | route/status-aware records с `source_url`, `content_sha256`, page/row locator |
| официальный PDF плана приёма | не включён в текущий captured fixture | source gap, не fabricated |

Если новый source добавляет квоты или уточняет размерность конкурса, это должно пройти через новый raw parser/normalizer и тот же canonical contract. Неподтверждённая или неоднозначная identity не записывается как связанная программа.

## API contract

```text
GET /programs/<program-id>/admissions
```

Ответ содержит:

- `program` и `programId`;
- `offerings[]` по году, `scope`, форме и типу финансирования;
- `places`, `exams`, `quotas`, `passingScores`, `tuition`;
- `provenance` с официальным source URL.

Для программы без admission-источника API возвращает `200` с `offerings: []`. Для неизвестного canonical ID возвращается strict `404 NOT_FOUND`. Decimal-поля приходят строками OpenAPI-контракта, например `"529000.00"` и `"46.00"`. Для `status=bvi` `score` приходит как `null`; новые поля `competitionType` и `status` присутствуют в server response.

## Migration and ingestion

Fixture SQLite smoke:

```powershell
python backend/scripts/run_andromeda_demo.py --mode fixture --check
```

Development PostgreSQL:

```powershell
$env:ANDROMEDA_ENV = "development"
$env:ANDROMEDA_DATABASE_URL = "postgresql+psycopg://andromeda:change-me@127.0.0.1:5432/andromeda_dev"
python -m alembic upgrade head
python backend/scripts/run_andromeda_ingestion.py --university bmstu --mode live --database-url $env:ANDROMEDA_DATABASE_URL
```

Runner applies Alembic before ingestion and synchronizes admissions atomically with programs and curricula. A repeated source snapshot is idempotent; stale rows for the affected program are reconciled inside the same transaction. Migration `0010_admission_passing_route` backfills old rows as `general + numeric`, adds nullable score support for BVI, and keys children by route/status/type. PostgreSQL и SQLite используют один repository port и одинаковые public contracts.

Для полного live-compatible запуска с диагностикой каталогов, order documents, numeric/BVI buckets и source gaps:

```powershell
python backend/scripts/run_andromeda_ingestion.py --university bmstu --mode live --database-url $env:ANDROMEDA_DATABASE_URL --log-level INFO
```

В live mode events/campus не заполняются fixture-данными: пока для них нет полноценного live source, они остаются пустыми.

## Manual browser check

1. Запустите `python backend/scripts/run_andromeda_demo.py --mode fixture`.
2. Откройте `http://127.0.0.1:3000/` и выберите «Программа».
3. Проверьте карточки 2026 budget/paid, `318`/`230` мест, ЕГЭ minimum `46`, стоимость `529000 ₽`, исторические проходные баллы и route labels/BVI, если order fixture подключён.
4. Переключите вторую программу в select и убедитесь, что hash, карточка и данные обновились.
5. Уменьшите viewport до ~390 px: select, карточки, ссылки источников и текст не должны выходить за экран или накладываться.

## See Also

- [API](api.md) — strict HTTP schemas и endpoints.
- [Архитектура](architecture.md) — границы modular monolith.
- [PostgreSQL](postgresql.md) — dev/staging migration flow.
