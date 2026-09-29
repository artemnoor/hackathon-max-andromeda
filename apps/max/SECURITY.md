# Security policy

Не коммить MAX bot tokens, Webhook secrets, Redis URLs with credentials, raw MAX initData, signed deep links, user profiles or runtime data. Используй локальный .env или secret manager.

MAX WebApp identity подтверждается только серверной HMAC-проверкой свежего initData. Не доверяй initDataUnsafe, userId/role из клиентского тела или auth в query string. Webhook требует HTTPS на внешнем edge, secret header, точный path и ограниченный request body. Callback payloads проходят allowlist. Redis outages fail closed in protected environments.

Не публикуй exploit details в открытом issue. Для отчёта используй GitHub private vulnerability reporting в настройках репозитория.
