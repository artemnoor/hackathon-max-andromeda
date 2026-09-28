# Инструкции для агентов

## Workflow

Проверь branch/status/history, прочитай README.md и docs/ перед изменениями. Сначала найди уже существующий MAX transport contract. Реализуй только подтверждённый scope; после изменений запусти релевантные тесты, typing/build, security/architecture checks и git diff --check.

## Архитектурные границы

- src/max владеет только MAX protocol/adapters.
- src/shared содержит transport-neutral config, errors, logging и Redis primitives, которые реально нужны MAX.
- miniapp содержит отдельную статическую оболочку и MAX Bridge adapter.
- MAX platform user ID не является Andromeda AccountId, auth role или правом доступа.
- Andromeda Public API client/auth exchange/business logic сейчас отсутствуют.
- Не добавляй generic plugin framework, product business modules, PostgreSQL schemas или migrations без отдельной задачи.
- MAX initData проверяется только на сервере; initDataUnsafe не является подтверждением личности.
- MAX credentials, raw initData, update bodies, user IDs и deep-link values не логируются.

## Git и секреты

Не меняй опубликованную историю. Не добавляй secrets, .env, generated runtime artifacts или .ai-factory/. Перед commit проверь cached paths. Коммиты создавай под identity пользователя из Git config.
