# Hackathon MAX Andromeda

Отдельный transport foundation для последующей реализации MAX Bot и MAX Mini App Andromeda. Репозиторий содержит только MAX transport runtime и Mini App shell. Основной Andromeda backend и Public API v1 живут в отдельном репозитории; соединение с ними пока не реализовано.

## Что уже есть

- MAX Bot polling/Webhook lifecycle с idempotent update handling и нейтральными `/start`/`/help` ответами.
- Проверка MAX Mini App `initData` на сервере; оболочка не создаёт сессию Andromeda и не сохраняет личные данные.
- Redis-backed rate limit, update leases и one-time deep-link state.
- Hardened MAX API fetch, URL allowlist, structured redacting logs, CSP и bounded static host.
- Docker Compose для локального Bot, Mini App и Redis; GitHub Actions CI.

## Границы продукта

Это не готовый бот Andromeda: команды не вызывают backend и не содержат приёмных сценариев. Здесь нет Andromeda API client, авторизации/связки аккаунта, бизнес-логики, личного маршрута или product navigation. Эти границы описаны в [architecture](docs/architecture.md).

## Локальный запуск

Требуются Node.js 22+, npm и Docker Compose. Скопируйте `.env.example` в `.env`, задайте тестовый/реальный `MAX_BOT_TOKEN`, затем запустите `docker compose up --build`. Mini App будет доступен на `http://localhost:8787`; Bot использует MAX polling transport. Никогда не коммитьте `.env`.

Для запуска без контейнеров используйте [development guide](docs/development.md). Для текущего поведения и проверок — [testing guide](docs/testing.md), для production deployment prerequisites — [deployment guide](docs/deployment.md).

MAX Bot и Mini App transport foundation готовы к отдельному этапу проектирования их функциональных границ. Не вводите backend routes или frontend API calls, пока эти границы и Public API integration contract не утверждены.
