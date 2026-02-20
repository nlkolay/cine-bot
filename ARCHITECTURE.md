# Архитектура Cine Bot

## Схема компонентов

```
SOURCE_CHANNELS                    TARGET_CHANNEL
(Telegram channels)                (Telegram channel)
        │                                 ▲
        │ новые посты                     │ отформатированные сообщения
        ▼                                 │
┌───────────────┐                  ┌───────────┐   send_message
│   Userbot     │─────────────────▶│  main.py  │──────────────────▶ Bot
│ (User API)    │  extract_with_   │           │
│ userbot.session  ocr             │ _process  │
└───────────────┘                  │  _titles  │
                                   └─────┬─────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
          ┌──────────────┐    ┌──────────────────┐  ┌─────────────────┐
          │ llm_client.py│    │  tmdb_client.py   │  │  arr_client.py  │
          │              │    │                    │  │                 │
          │ Gemini LLM   │    │  fallback chain:   │  │ Radarr (movie)  │
          │ + Vision OCR │    │  1. People API     │  │ Sonarr (tv)     │
          │              │    │  2. typed search   │  │                 │
          └──────────────┘    │  3. search/multi   │  └─────────────────┘
                              └────────┬───────────┘
                                       │ fetch_ratings(imdb_id)
                                       ▼
                              ┌─────────────────────┐
                              │    omdb_client.py    │
                              │  IMDb · RT · MC      │
                              │  genre · plot        │
                              └──────────────────────┘

          ┌──────────────┐
          │bot_settings.py│
          │               │
          │ settings.json │◄── /settings (inline buttons)
          │ persist       │
          └──────────────┘
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
NewMessage / Album (any chat)
  → проверка username ∈ settings.source_channels
  → _extract_with_ocr(message, client)
      → text-only (LLM / regex)
      → если fallback и нет результатов → retry с image
  → _process_titles(contexts) → list[MediaResult]
  → forward_messages + _post_results_to_channel
```

### OCR-режимы
```
"fallback" (по умолчанию):
  1. Извлечь из текста (LLM → regex)
  2. Если пусто и есть фото → повторить с image

"always":
  1. Скачать фото (если есть)
  2. Отправить text + image в LLM одним запросом
```

### DM-интерфейс
```
/start → приветствие
/search <query> → поиск в TMDb, результат в личку
/settings → admin-only inline-меню

<пересылка> + auto_post → forward + post в канал
<текст / фото> → extract → результаты в личку
<просто текст> → если нет titles → direct search
```

### Settings-меню (inline buttons)
```
/settings
  ├─ 🔄 OCR: Fallback/Always     → cycle
  ├─ ✅/❌ LLM extraction          → toggle
  ├─ ✅/❌ Auto-post forwards      → toggle
  ├─ 👥 Users (N)                  → sub-menu
  │    ├─ [user_id ✕]              → remove
  │    ├─ ➕ Add user               → admin state → next text = ID
  │    └─ ⬅️ Back
  └─ 📡 Channels (N)              → sub-menu
       ├─ [channel ✕]              → remove
       ├─ ➕ Add channel            → admin state → next text = username
       └─ ⬅️ Back
```

### Radarr/Sonarr (Grab)
```
CallbackQuery(grab:{type}:{tmdb_id}:{tvdb_id})
  → movie → add_to_radarr(tmdb_id)
  → tv    → add_to_sonarr(tvdb_id)
```

## Модули

### `config.py`
- Загрузка из `.env` через `python-dotenv`
- `TARGET_CHANNEL` парсится как `int` для числовых ID
- `ADMIN_USERS` — если пусто, fallback на `ALLOWED_USERS`

### `bot_settings.py`
- JSON-персистенция в `{SESSION_DIR}/settings.json`
- API: `get`, `set`, `toggle`, `cycle`, `add_to_list`, `remove_from_list`
- Сидирование: при первом запуске копирует `ALLOWED_USERS` и `SOURCE_CHANNELS` из env

### `extractor.py`
- `TitleContext` — dataclass: `title`, `year`, `director`, `is_english`
- Извлечение по кавычкам (`«»`, `""`, `„"`) → основной regex-путь
- Извлечение по bold-entities → запасной regex-путь
- `extract_titles_smart` — LLM-first + image support + regex fallback

### `llm_client.py`
- `GeminiProvider` — Google GenAI SDK
- Multimodal: text, image, или text+image
- Structured output через `response_schema=list[ExtractedTitle]`
- System prompt: извлечение + OCR из постеров

### `tmdb_client.py`
- `search(ctx: TitleContext)` — публичный API
- People API: `search/person` → `combined_credits` → fuzzy title match
- Typed search: `search/movie` + `search/tv` с year-фильтром
- Plain search: `search/multi` ru-RU → en-US
- `append_to_response=credits,external_ids` — один запрос вместо трёх

### `omdb_client.py`
- `fetch_ratings(imdb_id)` — IMDb рейтинг, Rotten Tomatoes, Metacritic, жанр, сюжет

### `arr_client.py`
- `add_to_radarr(tmdb_id, title)` — добавление фильма
- `add_to_sonarr(tvdb_id, title)` — добавление сериала
- Автоматический fetch quality profile и root folder

### `formatter.py`
- `format_result(r)` — HTML: заголовок, жанр, рейтинги, сюжет
- `build_buttons(r)` — inline-кнопки: IMDb · Trakt · Grab

## Бюджет API-вызовов на один тайтл

| Сценарий | Вызовы TMDb | Вызовы OMDb | Вызовы Gemini |
|---|---|---|---|
| Нет контекста | 2 (search/multi + details+append) | 0–1 | 0–1 |
| Только год | 2–4 (typed × 2 + details+append) | 0–1 | 0–1 |
| Год + режиссёр | 3–6 (People API + typed + details) | 0–1 | 0–1 |
| OCR fallback | как выше | 0–1 | 1–2 |
| OCR always | как выше | 0–1 | 1 |

## Деплой

```
docker compose build
docker compose up -d
```

Сессии и настройки хранятся в `./sessions/` (volume mount → `/data` внутри контейнера).
При первом запуске: положить код авторизации в `./sessions/auth_code.txt`.
