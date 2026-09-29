[← Архитектура](architecture.md) · [Admissions](admissions.md) · [Admission Fit](admission-fit.md)

# Admission Benefits: права, олимпиады и индивидуальные достижения

Andromeda хранит три разных вида данных, которые нельзя смешивать:

1. `admissions` — исторические наблюдения из приказов и конкурсных списков (`BVI` как статус зачисления, исторический проходной балл);
2. `admission_benefits` — source-backed правила приёма: какое право получает абитуриент при выполнении условий;
3. `admission_fit` — оценка готовности к обычному конкурсу. Она не превращает исторический BVI в юридическое право.

Правило права поступающего вычисляется детерминированно. Jev/LLM может помочь найти canonical Olympiad в интерфейсе, но не решает, есть ли БВИ, 100 баллов, подтверждение или прибавка за ИД.

## Generic policy integration

The `policy` module can select an approved source-backed revision that points
to an exact admission-benefit owner rule. It owns lifecycle, effective dates,
scope, exceptions, supersession and the structured resolution trace. It does
not duplicate this module's benefit semantics or eligibility calculation:
`AdmissionBenefitEvaluator` and the individual-achievement evaluator remain
the sole owners for BVI, 100 points, Olympiad confirmation/validity, special
routes and achievement points. Policy approval selects the exact owner
revision; the owner evaluator computes the domain outcome.

An existing `RuleDataStatus.ACTIVE` means the admission-benefit source rule is
usable by this owner module. It is not a generic policy approval event. Legacy
benefit data continue to serve their existing APIs; a generic policy revision
cannot resolve until its exact owner hash, evidence, cycle mapping and separate
human approval are present. See the [Knowledge and Policy architecture](architecture/knowledge-policy.md).

The assistant impact bridge accepts a short-lived `ApplicantAdmissionContext`
with typed facts and explicit completeness declarations for EGE scores,
internal exams, Olympiad results, individual achievements and applicant
category. It evaluates only when the approved policy trace selects the exact
hash of every active benefit rule for the requested program and the source
coverage is complete. Missing completeness, a stale hash or an incomplete
owner set produces unavailable/insufficient data. The bridge delegates to
`AdmissionDecisionService`; it does not store applicant facts as canonical
knowledge or infer that an omitted achievement is absent.

## Поток данных

```text
официальный индекс документов МГТУ
  → source snapshot (URL, hash, capture time)
  → raw table/HTML records
  → BMSTU parser + normalizer
  → canonical rules with status/provenance
  → PostgreSQL/SQLite repositories
  → catalog/reverse queries and AdmissionBenefitEvaluator
```

Каждая canonical rule содержит год приёма, тип права, результат (`winner`/`prize_winner`/`team_member`), область применения, условия подтверждения, статус (`active`, `review_required`, `conflict`, `stale`) и provenance с URL, hash и locator. `review_required` не становится действующим юридическим правилом.

## BMSTU 2026 source inventory

Источники обнаруживаются через официальный [раздел документов приёмной комиссии МГТУ](https://api.www.bmstu.ru/page/admission-committee-documents). В текущем implementation отдельно классифицируются Rules, приложения 5.x, отдельное Приложение 6 и Приложение 7.

- [Правила приёма 2026](https://api.www.bmstu.ru/file/124642/download) — общие условия и определения;
- [Приложение 5.1](https://api.www.bmstu.ru/file/124777/download) — таблицы прав БВИ и области направлений;
- [Приложение 5.3](https://api.www.bmstu.ru/file/122150/download) — отдельная таблица права на 100 баллов; её предмет и порог подтверждения не смешиваются с БВИ;
- [Приложение 6](https://api.www.bmstu.ru/file/125465/download) — перечень индивидуальных достижений бакалавриата/специалитета; текстовый extract хранит все позиции 1–46, табличные варианты баллов и сноски со страниц 7–8 (SHA-256 `5ae90e108dc8940b37fe3b07f211664b7871791792abdc6ddc0dd365fb948bb9`);
- приложение 5.2 и магистерское приложение 7 обнаруживаются динамически; строки, которые нельзя безопасно нормализовать, остаются source gaps/review;
- приложения 5.4 и 5.5 имеют отдельный table parser: ВОШ создаёт winner/prize-winner rules, международные олимпиады — team-member rules, с отдельными BVI/100-point mappings;
- приложения 8.1 и 8.3 захватываются как официальные snapshots, но относятся к квотам/целевому приёму и не превращаются в олимпиадные benefit rules до отдельной quota projection;
- официальные страницы олимпиады [«Шаг в будущее»](https://olymp.bmstu.ru/) используются как дополнительный официальный source для опубликованных условий профиля.

Минимизированные тестовые extracts сохраняют исходный URL, SHA-256 и page/table/row locator. Их содержимое не является новым canonical source: это воспроизводимые extracts оригинальных документов.

## Canonical semantics

`AdmissionBenefitRule` отдельно хранит:

- `BVI` — право на приём без обычных вступительных испытаний;
- `ONE_HUNDRED_POINTS` — 100 баллов по указанному предмету;
- `MAX_INTERNAL_EXAM_SCORE` и специальные/преимущественные маршруты как typed future-compatible routes;
- `scope`: `all`, `only`, `all_except`, с unresolved target, если код направления не сопоставлен;
- `confirmation_subjects` и `minimum_score`, если они явно извлечены;
- `validity`, включая год результата и срок действия, только если это подтверждено source.

Отсутствие порога, срока или области действия означает `unknown`/`review_required`, а не ноль и не универсальное право.

`IndividualAchievementPolicy` содержит правила ИД, баллы, категорию, документ-подтверждение и combination policy. Для МГТУ 2026 приложение 6 прямо разрешает суммировать разные достижения, но ограничивает общую сумму 10 баллами (сноска 2, стр. 7). Это сохраняется как `default_combination_policy=ADDITIVE` и `global_max_points=10`; provenance политики ведёт к официальной сноске, а provenance каждого достижения — к строке таблицы.

Сноска 4 (стр. 8) ограничивает повторное начисление одного основания и начисление внутри категории. Варианты одного нумерованного пункта, например золотый/серебряный/бронзовый знак ГТО, получают отдельные canonical codes, но объединяются общей source-row group с `MAX_ONLY`: несколько заявленных вариантов не суммируются. Дубликат одного canonical achievement/year засчитывается один раз; итоговая сумма дополнительно ограничивается source-backed общим cap. Распознавание сносок намеренно строгое: если обязательный текст отсутствует, конфликтует или не соответствует ожидаемой формулировке, policy остаётся `REVIEW_REQUIRED`/`UNKNOWN` и калькулятор не начисляет production points. Неизвестные категории/grounds не выводятся из памяти или предположения.

## API

```text
GET  /universities/{university_id}/admission-benefits?year=2026
GET  /programs/{program_id}/admission-benefits?year=2026&includeReview=true
GET  /admission-benefits/olympiads/{olympiad_id}/programs?university_id=...&year=2026
POST /programs/{program_id}/admission-eligibility
```

`includeReview=false` показывает только активные правила. `includeReview=true` нужен для аудита unresolved scope и source gaps.

`POST /programs/{program_id}/admission-eligibility` принимает ЕГЭ, внутренние экзамены, олимпиады и ИД. Ответ содержит route, status, breakdown, effective score и evidence. При БВИ effective score не используется как основной результат; при 100 баллах score change применяется только после проверки всех условий. Исторические observations не участвуют в этом вычислении.

## Offering-aware competitive score

The eligibility endpoint may select one source-backed `AdmissionOffering` by `offeringId`, or by the requested form/funding/campus. If none or multiple match, Andromeda does not pick an arbitrary offering. The response includes `competitiveScore`: selected offering, permitted exam combination, scores before/after rights, ID points, effective total, evidence and source gaps.

The legal route is evaluated first. Confirmed BVI makes the general competitive score `not_applicable`. Otherwise only required exams and source-defined choice-group cardinalities are counted; unused EGE scores are not added. A confirmed 100-point right replaces only its target subject, even when the applicant did not provide a raw score for that subject. Verified individual-achievement points are then composed under the persisted caps.

Olympiad/profile name resolution reads only the persisted source-backed catalog for the requested university and admission year. Exact deterministic matches bypass Jev. An unresolved candidate set may be sent to the optional bounded selector (maximum eight candidates), whose only valid output is one supplied canonical ID. Its dedicated production calibration lock is separate and opt-in. Jev never decides legal eligibility.

## Current data-quality boundary

Покрытие persisted snapshot проверяется командой `uv run --project backend --locked --extra dev python backend/scripts/check_bmstu_admission_benefits_release.py --year 2026`. Код `2` означает, что набор не готов к production serving: обязательные документы/парсинг неполны, есть конфликт или небезопасное активное правило. `review_required` строки видимы, но не считаются поддержанными правами. Нельзя заявлять «полностью покрыли МГТУ», если manifest показывает missing documents, unresolved targets, conflicts или review rows. Для неполного source run API возвращает status/provenance/source gaps, а не скрывает их пустым списком.

## Adding another university

Новый adapter размещается в `ingestion/universities/{university}/`. Он должен выдавать те же raw/canonical contracts и provenance. Domain `modules/admission_benefits` не знает о названии PDF-приложения, URL МГТУ или конкретной олимпиаде.
