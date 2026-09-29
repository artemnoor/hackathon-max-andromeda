# HSE ingestion

HSE подключается отдельным адаптером `backend/src/andromeda/ingestion/universities/hse`.
Адаптер использует только официальные публичные HSE-hosts и сохраняет каждый
полученный body как `RawSourceSnapshot` с `content_sha256`, URL, временем и
типом источника.

## Поток источников

| Этап | Официальный источник | Что извлекается |
| --- | --- | --- |
| Catalog | `admissions.hse.ru/undergraduate-apply/programmes_list` | ссылки на карточки программ всех кампусов, без списка кодов в коде |
| Detail | карточка каждой обнаруженной программы | название, кампусная карточка, уровень образования, education year, ссылка на study-plan page |
| Study plans | `/learn_plans/`, `/dbs/education/`, официальные `/mirror/pubs/share/` документы | work-plan PDFs, дисциплины, credits, hours, source position; learn-plan PDFs сохраняются для provenance |
| Admission rules | `ba.hse.ru/minkrit` | вступительные предметы, минимальные баллы, choice subjects |
| Places/quotas | `ba.hse.ru/kolmest` и официальные кампусные enrollment pages | budget/paid places, special/separate/targeted quota |
| Tuition | `ba.hse.ru/price` | стоимость платного обучения в RUB за academic year |
| Historical passing | ссылки `result20XX`, обнаруженные на admission site | historical numeric passing score с годом из URL |
| Enrolled | официальные списки Moscow, Saint Petersburg, Nizhny Novgorod, Perm | applicant rows, minimum `Сумма конкурсных баллов` по программе и competition type; BVI сохраняется как `status=bvi` без score |

Коды направления не угадываются по slug карточки. Если карточка не публикует
код, он связывается с официальным `minkrit` или заголовком work-plan PDF. При
неоднозначности создаётся `RawSourceGap`, а строка не попадает в canonical.

## Поведение при неполных источниках

HSE публикует не для каждой карточки стандартный `/learn_plans/` endpoint, а
часть PDF имеет различающиеся табличные шаблоны. Адаптер не подменяет такие
данные fixture-ами и не выводит часы из credits. Доступный официальный body
сохраняется, неподдержанная проекция фиксируется в `source_gaps`.

`HseUniversityAdapter` повторно безопасен: canonical program codes
детерминированно выводятся из официального detail URL, источники дедуплицируются
по `(kind, requested_url, content_sha256)`, а admission facts объединяются на
уровне offering с сохранением provenance.
