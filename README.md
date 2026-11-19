# Adrobot — обёртка над Keitaro

Веб-приложение поверх Admin API трекера [Keitaro](https://keitaro.io): создаёт
кампании по шаблону «гео → Google, остальные → оффер» и редактирует офферы уже
существующих кампаний, показывая по ним статистику.

**Стек:** FastAPI · SQLAlchemy 2 (async) · Alembic · httpx · Pydantic v2 ·
ванильный ES-модульный фронтенд (без сборки).

---

## Что умеет

### 1. Создаватор кампаний

Принимает **название**, **гео-код страны** и **ID оффера** и создаёт в Keitaro
кампанию с настроенными доменом, группой и источником, а в ней — два потока:

| № | Поток | Схема | Что делает |
|---|-------|-------|------------|
| 1 | `GEO XX -> redirect` | `redirect` / `http` | фильтр `country = [XX]`, редирект на `https://google.com` |
| 2 | `Offers` | `landings` | весь остальной трафик ротируется на выбранный оффер |

Ротация потоков — **по позиции**, поэтому поток 1 проверяется первым и
перехватывает нужную страну, а всё остальное проваливается в поток 2.

Название автоматически получает командный префикс (`CAMPAIGN_NAME_PREFIX`,
например `test_rozhkov_`) и не дублирует его, если он уже есть.

Если создать потоки не удалось, кампания удаляется — недособранных кампаний в
трекере не остаётся.

### 2. Редактор кампании

Редактор работает **по модели «черновик → публикация»**, как в эталонном
инструменте из ТЗ: правки живут в нашей базе и уходят в Keitaro только по явной
команде.

| Кнопка | Что делает |
|--------|-----------|
| **Fetch streams** | забирает потоки кампании из Keitaro в локальную рабочую копию |
| добавить / **Remove** / **Bring back** / пин доли | меняют **только** черновик, Keitaro не трогают |
| **Push to Keitaro** | заливает все неопубликованные потоки в трекер |
| **Cancel** | откатывает черновик к последнему известному состоянию Keitaro |

Как это выглядит:

* поток с неопубликованными изменениями **желтеет** и получает бейдж «не опубликовано»;
* удалённый оффер не исчезает: он **серый, с долей 0%**, остаётся в архиве и возвращается кнопкой **Bring back**;
* **доли пересчитываются автоматически** и всегда дают в сумме 100%;
* **закреплённая доля** (пин 📌) переживает любые пересчёты — остальные офферы делят остаток;
* если оффер удалили **руками в Keitaro**, повторный Fetch не теряет его, а переводит в тот же архивный статус — его тоже можно вернуть;
* потоки без офферов отслеживаются, но их содержимое не редактируется. В отличие от эталона мы всё же показываем у них фильтр по стране и URL редиректа — это дешёво и помогает понять, что за поток.

Ради этого в проекте и нужен SQLAlchemy: `tracked_campaigns` / `tracked_streams` /
`tracked_offers` — это рабочая копия, а не кэш. У каждого оффера два состояния:
`state` (чего хочет оператор) и `synced_state` (что, по нашим данным, лежит в
Keitaro). Разница между ними и есть «не опубликовано».

---

## Быстрый старт

Нужен **Python 3.12+**.

### Вариант A — [uv](https://docs.astral.sh/uv/) (рекомендуется)

```bash
uv sync --dev
```

### Вариант B — pip

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[postgres]" --group dev
```

### 1. Конфигурация

```bash
cp .env.example .env
```

Заполните в `.env` как минимум:

```bash
KEITARO_API_KEY=<ключ из Keitaro: Профиль → API ключи → Создать новый ключ>
SESSION_SECRET=<сгенерировать, см. ниже>
CAMPAIGN_NAME_PREFIX=test_rozhkov_
```

Секрет сессий:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. Миграции

```bash
alembic upgrade head
```

Откатить всё: `alembic downgrade base`. Создать новую миграцию после изменения
моделей: `alembic revision --autogenerate -m "описание"`.

### 3. Учётная запись оператора

```bash
adrobot create-user --email you@example.com
```

Пароль спрашивается интерактивно (минимум 12 символов) — он не попадает ни в
историю shell, ни в список процессов. Команда же пересоздаёт пароль, если
пользователь уже есть.

Альтернатива для контейнеров — переменные `BOOTSTRAP_USER_EMAIL` /
`BOOTSTRAP_USER_PASSWORD`: аккаунт создастся при первом старте, существующий
пароль при этом не трогается.

### 4. Проверка связи с Keitaro

```bash
adrobot check-keitaro
```

```
Keitaro at https://tlgk.host is reachable:
  offers:         128
  domains:        3
  groups:         5
  traffic sources:4
```

### 5. Запуск

```bash
uvicorn app.main:app --reload --port 8000
```

* UI — <http://127.0.0.1:8000/>
* Swagger — <http://127.0.0.1:8000/docs> (выключен при `ENVIRONMENT=production`)

> По http куки с флагом `Secure` не сохраняются, поэтому для локального запуска
> в `.env` должно быть `COOKIE_SECURE=false`. В production это значение
> запрещено — приложение не стартует.

---

## Тесты

```bash
pytest                      # весь набор
pytest -m "not slow"        # без тестов, запускающих Alembic
pytest --cov=app --cov-report=term-missing
```

Покрытие — **94 %**, 273 теста. Сеть не требуется: вместо трекера используется
`tests/fakes.py::FakeKeitaro` (реализация `KeitaroPort` в памяти), а HTTP-слой
проверяется через `respx`.

Линтер и типы:

```bash
ruff check . && mypy app
```

---

## Архитектура

```
app/
├── core/            конфигурация, безопасность, логирование, DI-контейнер
│   ├── config.py        Settings (pydantic-settings, SecretStr)
│   ├── container.py     композиционный корень: здесь собирается весь граф
│   ├── exceptions.py    доменные исключения → HTTP-статус + безопасный текст
│   ├── geo.py           ISO 3166-1 alpha-2
│   ├── logging.py       редактирование секретов в логах
│   ├── rate_limit.py    sliding window
│   └── security.py      Argon2id, подписанные сессии, CSRF
├── db/              Base, модели, фабрика сессий
├── keitaro/         всё, что знает про Keitaro
│   ├── client.py        транспорт: заголовок Api-Key, ретраи, маппинг ошибок
│   ├── gateway.py       типизированный фасад (URL-ы и парсинг JSON)
│   ├── builders.py      сборка payload-ов (все константы Keitaro — здесь)
│   ├── models.py        pydantic-модели сущностей трекера
│   └── protocols.py     узкие интерфейсы для сервисов
├── services/        сценарии
│   ├── campaign_creator.py  создание кампании с двумя потоками
│   ├── draft.py             черновик редактора: fetch, правки, publish, cancel
│   ├── catalog.py           справочники Keitaro + TTL-кэш
│   └── stats.py             отчёты и нормализация метрик
├── schemas/         DTO нашего API
├── api/             роутеры, зависимости, middleware, обработчики ошибок
└── web/static/      UI: HTML + CSS + ES-модули
```

Принципы, которым следует код:

* **SRP** — транспорт (`client.py`), маппинг (`gateway.py`), сборка payload-ов
  (`builders.py`) и бизнес-логика (`services/`) разделены.
* **DIP** — сервисы зависят от `Protocol`-ов (`CatalogReader`, `StreamWriter`, …),
  а не от конкретного шлюза. Благодаря этому тесты подставляют `FakeKeitaro`
  одной строкой, без патчинга импортов.
* **ISP** — вместо одного «толстого» интерфейса пять узких.
* **DRY** — распределение долей, нормализация имени, автокомплит на фронте и
  обработка ошибок существуют ровно в одном месте.
* **KISS** — никаких очередей, кэшей-демонов и самописных ORM: SQLite по
  умолчанию, TTL-кэш на 60 секунд, фронтенд без сборки.

### Что хранится в БД

Keitaro остаётся источником истины. Локально хранится только то, чего в нём нет:

| Таблица | Назначение |
|---------|-----------|
| `users` | учётные записи операторов (Argon2id-хеши) |
| `campaign_records` | история кампаний, созданных через Adrobot |
| `audit_log` | кто, что и когда менял; входы и неудачные попытки входа |
| `tracked_campaigns`, `tracked_streams`, `tracked_offers` | рабочая копия редактора: черновик потоков и офферов до публикации |

---

## API

Все эндпоинты, кроме `/health`, требуют сессии; изменяющие — ещё и заголовок
`X-CSRF-Token`.

| Метод | Путь | Назначение |
|-------|------|-----------|
| `POST` | `/api/v1/auth/login` | вход, выдаёт куку и CSRF-токен |
| `POST` | `/api/v1/auth/logout` | выход |
| `GET` | `/api/v1/auth/session` | текущая сессия |
| `GET` | `/api/v1/offers?q=&limit=` | автокомплит по офферам |
| `GET` | `/api/v1/countries` | список стран |
| `GET` | `/api/v1/domains`, `/groups`, `/sources` | справочники Keitaro |
| `GET` | `/api/v1/campaign-defaults` | домен/группа/источник по умолчанию |
| `POST` | `/api/v1/campaigns` | **создать кампанию** |
| `GET` | `/api/v1/campaigns?q=&limit=` | список кампаний |
| `POST` | `/api/v1/campaigns/{id}/fetch` | **Fetch streams** — забрать потоки в черновик |
| `GET` | `/api/v1/campaigns/{id}/draft?days=` | черновик + статистика (404, пока не забирали) |
| `POST` | `/api/v1/campaigns/{id}/offers` | добавить оффер в черновик |
| `DELETE` | `/api/v1/campaigns/{id}/offers/{offer_id}` | пометить оффер удалённым |
| `POST` | `/api/v1/campaigns/{id}/offers/{offer_id}/restore` | **Bring back** |
| `PUT` | `/api/v1/campaigns/{id}/offers/{offer_id}/pin` | закрепить / отпустить долю |
| `POST` | `/api/v1/campaigns/{id}/publish` | **Push to Keitaro** |
| `POST` | `/api/v1/campaigns/{id}/discard` | **Cancel** — откатить черновик |

Ошибки всегда одного вида — `{"code": "...", "message": "..."}`, без внутренних
деталей и трейсбеков.

<details>
<summary>Пример: создание кампании</summary>

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"name": "campaign1", "geo": "AU", "offer_id": 3749}'
```

```json
{
  "campaign": {"id": 512, "name": "test_rozhkov_campaign1", "alias": "wVqN1R"},
  "tracking_url": "https://in.posdk.xyz/wVqN1R",
  "geo": "AU", "geo_name": "Australia",
  "redirect_url": "https://google.com",
  "offer_id": 3749, "offer_name": "Miaflow [BEAUTY-RO-BE_0009]",
  "defaults": {"domain_name": "in.posdk.xyz", "group_name": "FORTESTS", "source_name": "FORTESTS"},
  "streams": [
    {"name": "GEO AU -> redirect", "position": 1, "countries": ["AU"], "redirect_url": "https://google.com"},
    {"name": "Offers", "position": 2, "holds_offers": true}
  ]
}
```
</details>

---

## Особенности Admin API, которые пришлось выяснить опытным путём

Документация в админке неполная, поэтому реальные требования проверены живыми
запросами. Всё это зафиксировано константами в `app/keitaro/builders.py` и
тестами, чтобы не выяснять заново.

| Что | Как на самом деле |
|-----|-------------------|
| Группы кампаний | `GET /groups` **требует** `type`, и значение во множественном числе: `campaigns`, `offers`. Без него — `Param 'type' is required`, с `type=campaign` — пустой список |
| Источник трафика | в кампании поле называется `traffic_source_id`, а не `source_id` |
| Алиас | `alias` обязателен при создании и Keitaro его **не** генерирует: `{"alias": ["Alias is required"]}`. Генерируем сами, 10 символов `[A-Za-z0-9]` |
| Схема потока-редиректа | `schema: "redirect"` (не `"action"`), плюс `action_type: "http"` и `action_payload: "<url>"` |
| `action_type` | обязателен на **любом** потоке, включая `schema: "landings"`, где действия нет: `{"action_type": ["Action Type is required"]}` |
| Фильтр по стране | `{"name": "country", "mode": "accept", "payload": ["AU"]}` — payload списком, коды в верхнем регистре |
| Удаление кампании | `DELETE /campaigns/{id}` отправляет кампанию в архив, а не стирает: повторное создание с тем же именем падает с `Name has already been used in the archive` |
| Формат ошибок | валидация возвращает `{"поле": ["сообщение"]}` без общей обёртки — клиент разбирает и такой формат, иначе пользователь видел бы бесполезное «Keitaro rejected the request payload» |
| Отчёты | `POST /report/build` отдаёт `{"rows": [...], "total": N}`; уникальные клики называются `campaign_unique_clicks` |

### Проверено на живом трекере

Создана кампания `test_rozhkov_campaign1` (id **215313**,
<https://kylovoa.com/E4WBH9InOu>) — ровно та структура, что в ТЗ:

```
#1 'GEO AU -> redirect'  schema=redirect  http -> https://google.com
   filters=[('country', 'accept', ['AU'])]
#2 'Offers'              schema=landings  offers=[(18813, 100%)]
   type=position  cost=CPC 0 USD (cost_auto)  group=FORTESTS  source=FORTESTS
   domain=kylovoa.com
```

Полный цикл редактора прогнан на ней же, против живого трекера:

| Шаг | Что в черновике | Что в Keitaro |
|-----|-----------------|---------------|
| до `fetch` | 404 `campaign_not_tracked` | — |
| `fetch` | `18813 · 100% · active` | `18813 · 100%` |
| `remove` | `18813 · 0% · removed`, dirty | **не изменилось** |
| `cancel` | `18813 · 100% · active`, чисто | не изменилось |
| `remove` + `publish` | `removed`, чисто | **пусто** |
| `bring back` + `publish` | `active · 100%` | `18813 · 100%` |
| оффер удалён прямо в Keitaro → `fetch` | `removed` (не потерян), чисто | пусто |

Цифры сверены с `report/build` напрямую: для кампании 215192 и API, и UI
показывают 15 кликов / 1 уникальный / 0 конверсий.

---

## Безопасность

| Угроза | Мера |
|--------|------|
| Утечка ключа Keitaro | только из env, `SecretStr`, не попадает в API-ответы; фильтр логов вырезает ключи, токены и `Authorization` |
| Доступ посторонних | сессия в подписанной куке `HttpOnly` + `SameSite=Strict` + `Secure`; Argon2id (OWASP-параметры) |
| CSRF | double-submit токен на всех небезопасных методах |
| Подбор пароля | rate limit по `IP + email`, одинаковый ответ и одинаковое время для «нет пользователя» и «неверный пароль» |
| Перечисление пользователей | единый текст ошибки `Invalid email or password.` |
| XSS | строгий CSP (`default-src 'self'`, без `unsafe-inline`), на фронте только `textContent`, нигде нет `innerHTML` |
| Clickjacking | `X-Frame-Options: DENY`, `frame-ancestors 'none'` |
| SSRF через API-путь | путь к Keitaro собирается только внутри пакета и проверяется: запрещены `//`, `..`, query и любые схемы |
| Подмена хоста редиректом | редиректы не выполняются; `3xx` от трекера — ошибка, а не повод отправить `Api-Key` на чужой хост |
| Дублирование POST при ретрае | ретраятся только идемпотентные методы |
| DoS телом запроса | лимит на размер тела (413) + общий rate limit API |
| Обход лимитов через заголовки | `X-Forwarded-For` намеренно игнорируется |
| Небезопасный прод | `ENVIRONMENT=production` требует ключ, секрет ≥ 32 символов, `COOKIE_SECURE=true` и запрещает `DEBUG`; Swagger выключается |
| Утечки в ответах | единый обработчик ошибок, наружу уходит только безопасный текст |
| Секреты в аудите | ключи вида `password`, `token`, `api_key`, `cookie` вырезаются перед записью |

Аудит неудачного входа коммитится отдельно — иначе он откатывался бы вместе с
транзакцией запроса (этот баг нашёл тест `test_failed_logins_are_audited`).

---

## Конфигурация

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `ENVIRONMENT` | `local` | `local` / `staging` / `production` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./adrobot.db` | для PostgreSQL — `postgresql+asyncpg://…` |
| `KEITARO_BASE_URL` | `https://tlgk.host` | адрес трекера |
| `KEITARO_API_KEY` | — | ключ Admin API |
| `KEITARO_TIMEOUT_SECONDS` | `20` | таймаут запроса |
| `KEITARO_MAX_RETRIES` | `2` | ретраи идемпотентных запросов |
| `KEITARO_CACHE_TTL_SECONDS` | `60` | кэш справочников |
| `KEITARO_DEFAULT_DOMAIN` / `_GROUP` / `_SOURCE` | — | предпочитаемые домен/группа/источник по имени |
| `CAMPAIGN_NAME_PREFIX` | `test_` | префикс имени кампании |
| `GEO_REDIRECT_URL` | `https://google.com` | куда уводит первый поток |
| `SESSION_SECRET` | — | ключ подписи сессий (≥ 32 символов) |
| `SESSION_TTL_SECONDS` | `28800` | срок жизни сессии |
| `COOKIE_SECURE` | `true` | `false` только для локального http |
| `LOGIN_RATE_LIMIT_*` | `5` / `300 с` | лимит попыток входа |
| `API_RATE_LIMIT_*` | `120` / `60 с` | лимит запросов к API |
| `MAX_REQUEST_BODY_BYTES` | `65536` | максимальный размер тела |
| `CORS_ORIGINS` | — | список через запятую; нужен, только если UI на другом домене |

---

## Ограничения и что стоит доделать

* Rate limit и кэш справочников живут в памяти процесса: при нескольких воркерах
  нужен Redis. Интерфейсы (`RateLimiter`, `TTLCache`) под замену уже готовы.
* Роли пока нет — все операторы равны.
* Публикация делает `PUT` на поток целиком — трекер не умеет «добавь один
  оффер». Если между `fetch` и `publish` кампанию правили в Keitaro, публикация
  перетрёт те правки. Кнопка Fetch streams показывает расхождение, но
  автоматической проверки версии перед записью нет — её я бы добавил следующей.
* Черновик один на всех операторов: это рабочая копия инструмента, а не
  личная песочница каждого пользователя.
* Статистика берётся из `report/build` и кэшем не покрыта: каждое открытие
  кампании — два запроса к трекеру.
* Тестовому API-ключу виден ровно один оффер, один домен и один источник,
  поэтому ротацию нескольких офферов вживую показать негде — она покрыта
  тестами (`test_campaign_editor.py`, `test_builders.py`).
* После отката создания кампании её имя остаётся занятым в архиве Keitaro,
  так что повторная попытка с тем же названием не пройдёт. Сейчас
  пользователь видит текст ошибки от трекера; по-хорошему стоит предлагать
  имя с суффиксом.
