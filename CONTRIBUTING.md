# Разработка

Создавай feature branch от main, сохраняй границы MAX Bot / Mini App / shared infrastructure и не добавляй Andromeda product/API integration без отдельного scope.

До отправки изменений выполни clean install, typecheck, lint, unit/integration/browser tests, build, configuration/architecture/secret/documentation checks и git diff --check. Не добавляй локальные .env, .ai-factory/, build/test output или secrets.