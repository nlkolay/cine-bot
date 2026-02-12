# Архитектура Cine Bot

## Схема компонентов

```
SOURCE_CHANNELS                    TARGET_CHANNEL
(Telegram channels)                (Telegram channel)
        │                                 ▲
        │ новые посты                     │ отформатированные сообщения
        ▼                                 │
┌───────────────┐   extract_titles   ┌───────────┐   send_message
│   Userbot     │──────────────────▶ │  main.py  │──────────────────▶ Bot
│ (User API)    │                    │           │
│ userbot.session│                   │ _process  │
└───────────────┘                   │  _titles  │
                                    └─────┬─────┘
                                          │ search(TitleContext)
                                          ▼
                              ┌────────────────────────┐
                              │     tmdb_client.py      │
                              │                         │
                              │  fallback chain:        │
                              │  1. year + director     │
                              │     → typed search      │
                              │     → credits check     │
                              │  2. year only           │
                              │     → typed search      │
                              │  3. no context          │
                              │     → search/multi      │
                              └──────────┬─────────────┘
                                         │ fetch_ratings(imdb_id)
                                         ▼
                              ┌─────────────────────┐
                              │    omdb_client.py   │
                              │  IMDb · RT · MC     │
                              │  genre · plot       │
                              └─────────────────────┘
```

## Два клиента Telegram

| | Userbot | Bot |
|---|---|---|
| API | MTProto (User API) | Bot API (bot token) |
| Аутентификация | Номер телефона + код | `BOT_TOKEN` |
| Сессия | `userbot.session` | `bot.session` |
| Что делает | Читает SOURCE_CHANNELS | Пишет в TARGET_CHANNEL, обрабатывает DM |
| Зачем нужен | Может читать любой публичный канал | Бот не может вступать в каналы сам |

## Потоки данных

### Основной (канал → канал)
```
NewMessage(SOURCE_CHANNELS)
  → extract_titles(message) → list[TitleContext]
  → _process_titles(contexts) → list[MediaResult]
  → _send_results(results, source_text)
      → format_source(text) → bot.send_message (цитата)
      → format_result(r) + build_buttons(r) → bot.send_message × N
```

### DM-интерфейс
```
/search <query>
  → TitleContext(title=query)  ← без year/director
  → search(ctx) → MediaResult
  → event.respond(...)  ← только в личку, не в канал

<свободный текст>
  → extract_titles(message) → list[TitleContext]
  → _process_titles(contexts) → list[MediaResult]
  → _send_results(...)  ← постит в канал
  → event.respond("Posted N result(s)...")
```

## Модули

### `extractor.py`
- `TitleContext` — dataclass: `title`, `year`, `director`
- Извлечение по кавычкам (`«»`, `""`, `„"`) → основной путь
- Извлечение по bold-entities → запасной путь
- Год: ближайшее `\b(19\d{2}|20[0-2]\d)\b` к позиции тайтла
- Режиссёр: имя после закрывающей кавычки или после ключевых слов `режиссёр`/`снявший`

### `tmdb_client.py`
- `search(ctx: TitleContext)` — публичный API
- `_search_with_context` — при наличии year/director:
  - `_search_typed` × 4 (movie+tv × ru-RU+en-US) с year-фильтром
  - Проверка режиссёра через `append_to_response=credits,external_ids` (top-3)
  - `_names_match` — сравнение по 4-символьным стемам (для склонений)
- `_search_plain` — fallback: `search/multi` ru-RU → en-US
- `_get_details` — один запрос вместо двух (details + external_ids + credits)

### `omdb_client.py`
- `fetch_ratings(imdb_id)` — IMDb рейтинг, Rotten Tomatoes, Metacritic, жанр, сюжет
- Возвращает `None` если `OMDB_API_KEY` не задан

### `formatter.py`
- `format_result(r)` — HTML: эмодзи-заголовок, жанр, рейтинги, сюжет
- `format_source(text)` — цитата оригинального поста (`<blockquote>`)
- `build_buttons(r)` — inline-кнопки: TMDb · IMDb · Trakt.tv

### `config.py`
- Загрузка из `.env` через `python-dotenv`
- `TARGET_CHANNEL` парсится как `int` для числовых ID

## Бюджет API-вызовов на один тайтл

| Сценарий | Вызовы TMDb | Вызовы OMDb |
|---|---|---|
| Нет контекста | 2 (search/multi + details+append) | 0–1 |
| Только год | 2–4 (typed × 2 + details+append) | 0–1 |
| Год + режиссёр | 3–6 (typed × 2 + details × 1–3) | 0–1 |

`append_to_response=credits,external_ids` объединяет `external_ids` и `credits` в один запрос.

## Деплой

```
docker compose build
docker compose up -d
```

Сессии хранятся в `./sessions/` (volume mount → `/data` внутри контейнера).
При первом запуске: положить код авторизации в `./sessions/auth_code.txt`.
