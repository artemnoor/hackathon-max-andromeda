[← Admissions](admissions.md) · [Back to README](../README.md) · [Конфигурация →](configuration.md)

# Admission Fit

`Admission Fit` — отдельная оценка реалистичности поступления на одну выбранную образовательную программу и один конкретный admission offering. Она использует введённые баллы абитуриента и реальные admissions facts из Andromeda API.

Это не обещание зачисления и не Content Fit. Результат не участвует в ranking `/recommendations`, не меняет `UserProfile` и не смешивается с `Career Fit` или `Workload readiness`.

## Пользовательский flow

1. Откройте в UI раздел «Программа».
2. Дождитесь блока `Admission Fit` под карточками поступления.
3. Выберите год, форму, тип финансирования и scope в поле «Набор для сравнения».
4. Введите известные баллы по показанным ЕГЭ. Пустые поля можно оставить пустыми.
5. Нажмите «Рассчитать Admission Fit».

Результат показывает score `0..100`, статус, качество данных, три компонента оценки, совпадения, причины снижения и пробелы данных. Ссылки в объяснениях ведут на provenance официального источника.

## Источник данных и границы

```text
GET /programs/{id}/admissions
  → выбранный offering.exams и passingScores
  → POST /programs/{id}/admission-fit
  → AdmissionFitService
  → AdmissionFitScoringService
```

Admission Fit читает только публичные contracts `ProgramReader` и `AdmissionReader` через собственный reader port. ORM и таблицы не становятся контрактом модуля. В текущем BMSTU fixture доступны требования ЕГЭ и минимумы, а также часть проходных баллов; для отдельных наборов исторические или квотные значения могут отсутствовать. Отсутствие факта отображается как `dataGaps`, а не как ноль.

## API

### Request

```http
POST /programs/program:09.03.01-02/admission-fit
Content-Type: application/json
```

```json
{
  "version": 1,
  "offeringId": "admission-offering:program:09.03.01-02:2026:unknown:budget:direction",
  "applicant": {
    "version": 1,
    "scores": [
      {"subject": "Математика", "score": 90},
      {"subject": "Русский язык", "score": 88},
      {"subject": "Информатика", "score": 92}
    ]
  }
}
```

`offeringId` должен быть взят из фактического ответа `GET /programs/{id}/admissions`: не следует вручную угадывать год или тип набора. Каждая оценка находится в диапазоне `0..100`. Контракт строгий (`extra="forbid"`); повтор одного предмета после нормализации считается ошибкой.

Пример с fixture API в PowerShell:

```powershell
$base = "http://127.0.0.1:8000"
$admissions = Invoke-RestMethod "$base/programs/program:09.03.01-02/admissions"
$offering = @($admissions.offerings | Where-Object { $_.exams.Count -gt 0 })[0]
$body = @{
  version = 1
  offeringId = $offering.id
  applicant = @{
    version = 1
    scores = @($offering.exams | ForEach-Object {
      @{ subject = $_.subject; score = 90 }
    })
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod "$base/programs/program:09.03.01-02/admission-fit" -Method Post -ContentType "application/json" -Body $body
```

### Response

Ответ `AdmissionFitResponse` содержит:

| Поле | Смысл |
|---|---|
| `programId`, `offeringId`, `admissionYear` | Каноническая программа и выбранный набор |
| `studyForm`, `fundingType` | Форма обучения и финансирование offering |
| `status`, `score` | Итоговый отдельный Admission Fit |
| `dataQuality` | `complete`, `partial` или `unavailable` |
| `breakdown` | `minimumReadiness`, `passingReadiness`, `dataCompleteness` |
| `reasons` | Факты, поддерживающие результат |
| `antiReasons` | Факты, снижающие реалистичность |
| `dataGaps` | Неизвестные или неоднозначно сопоставленные факты |

Decimal-поля (`applicantTotalScore`, значения метрик и reference scores) сериализуются строками. Каждый reason сохраняет provenance, когда объяснение опирается на конкретную запись источника.

## Subject identity

Система сохраняет исходное название предмета. Сопоставление выполняется детерминированно: Unicode normalization, case folding, нормализация пробелов и небольшой список явных aliases (`ё/е`, русский/английский и некоторые варианты названий ЕГЭ). Fuzzy matching не используется.

Если введённое название нельзя сопоставить или оно подходит нескольким кандидатам, предмет не выбирается автоматически. Такой факт попадает в `dataGaps`, а результат не притворяется полным.

Обязательными для оценки считаются только exams с `isRequired=true` и `isChoice=false`. Предметы «на выбор» не превращаются в обязательный экзамен без отдельного канонического решения о выбранной группе.

## Scoring

Расчёт использует только обязательные сопоставленные exams и опубликованные facts выбранного offering.

### Компоненты

- `minimumReadiness` — среднее по предметам значение `clamp(applicantScore / minimumScore, 0, 1) × 100` для опубликованных минимумов. Если минимум не опубликован, он не выдумывается.
- `passingReadiness` — `clamp(sum(matchedApplicantScores) / selectedPassingScore, 0, 1) × 100`. Сначала выбирается проходной балл того же funding type (`budget`/`paid`), затем fallback `average`/`other`.
- `dataCompleteness` — доля сопоставленных обязательных exams.

Итоговая формула:

```text
score = round_half_up(
  (0.50 × minimumReadiness
   + 0.35 × passingReadiness
   + 0.15 × dataCompleteness)
  / сумму весов доступных компонентов
)
```

Если компонент недоступен, его вес исключается из знаменателя. Это делает отсутствие данных явным и не превращает его в нулевую успеваемость. Score ограничен `0..100` и округляется до целого.

### Статусы

| Статус | Правило |
|---|---|
| `realistic` | Нет нарушения известного минимума, обязательные данные сопоставлены, passing readiness `100`, итоговый score не ниже `80` |
| `borderline` | Данные обязательных exams полные, но passing readiness ниже `100` и не ниже `85`, либо итоговый score `55..79` |
| `unlikely` | Нарушен известный минимум, passing readiness ниже `85` или итоговый score ниже `55` |
| `insufficient_data` | Не указан обязательный балл или нет доступных компонентов для оценки |

Нарушение известного минимума имеет приоритет над высоким итоговым score и не может дать статус `realistic`. Неизвестный минимум сам по себе не считается провалом.

## Ошибки и ограничения

- `404 NOT_FOUND` — canonical program или выбранный offering не найден.
- `422 VALIDATION_ERROR` — неизвестные поля, неверный диапазон score, пустой subject или нарушен strict contract.
- `200` с `insufficient_data` — программа существует, но опубликованных фактов или введённых баллов недостаточно для уверенной оценки.

Admission Fit не учитывает конкурс текущего года в реальном времени, индивидуальные льготы, документы, целевое поступление, олимпиадные права и вероятность зачисления, если эти факты не представлены admissions contract. Поэтому score следует читать как explainable readiness signal по доступным опубликованным данным.

## See Also

- [Admissions](admissions.md) — source-backed условия поступления и provenance.
- [API](api.md) — полный HTTP/OpenAPI reference.
- [Тестирование](testing.md) — unit, integration и browser checks.
