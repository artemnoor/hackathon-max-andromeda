# Инструкции для AI-агентов Andromeda

Этот файл — обязательный первый контекст для любой работы в репозитории. Цель агента — выполнить запрошенную задачу в текущей архитектуре Andromeda, сохранить проверяемость изменений и передать следующему агенту факты, а не предположения.

## Обязательный workflow

Работай последовательно:

`context → analysis → plan → implementation → tests → verification`

1. `context`: прочитай этот файл, `.ai-factory/config.yaml` (если существует), resolved `DESCRIPTION.md` и `RULES.md`, `README.md`, релевантные `docs/`, текущую ветку, статус и историю. Для архитектурной задачи также проверь `docs/architecture.md`, composition/API/infrastructure, существующие contracts, ports и tests.
2. `analysis`: опиши фактические точки входа, владельца данных, public contracts, зависимости и ограничения. Ищи существующий модуль/контракт прежде, чем создавать новый.
3. `plan`: зафиксируй scope, не затрагиваемые части, точные файлы/символы и проверяемые acceptance criteria. Если задача шире запроса или требует нового архитектурного решения, остановись на границе и запроси решение.
4. `implementation`: меняй только согласованный scope. Используй существующие canonical IDs, typed contracts и module boundaries. Business logic не выноси в API, composition или случайный shared helper.
5. `tests`: добавь/обнови тесты для изменённого поведения и boundary; запускай узкие проверки после каждого существенного изменения, затем полный релевантный набор.
6. `verification`: проверь `git diff --check`, status, тесты, typing/build и документацию. Для contract/API изменений проверь OpenAPI и generated clients. Перед handoff перечисли изменённые файлы, команды и результаты.

## Scope и безопасность

- Не меняй product scope без явного запроса. Не начинай Personal Route, новую карту или другой feature из соседнего плана.
- Не делай `git reset --hard`, force-push, rebase опубликованной истории, массовое удаление, перезапись `main` или удаление пользовательских файлов. Ветки создавай только когда это нужно workflow; main интегрируй обычным проверяемым merge.
- Не удаляй и не перезаписывай pre-existing untracked files. Перед commit проверь `git diff --cached --name-only` и добавляй только ожидаемые пути.
- Не добавляй secrets, tokens, cookies, database URLs или полные пользовательские профили в код, fixtures, логи и отчёты.
- Не скрывай failing check изменением CI/workflow. Исправляй первопричину или явно передавай blocker.

## Архитектурный default

Andromeda — modular monolith. Сначала используй существующие `contracts.public`, typed Protocol ports и repositories; новый модуль/интеграция требуют отдельного обоснования. Subject modules не знают об ORM, FastAPI или university-specific parser. После изменений обязательно оставь runnable evidence для следующего агента.

Эти инструкции задают repository-wide workflow и safety rules. Архитектурные правила ниже применяются к core Andromeda; бывший `proftest-spike` retired и описан только в архивной non-executable заметке, поэтому не должен возвращаться как отдельный runtime.
