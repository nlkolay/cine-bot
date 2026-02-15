<p align="center">
  <img src="assets/banner.svg" alt="Cine Bot" width="900"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Telethon-MTProto-green?style=flat-square" alt="Telethon"/>
  <img src="https://img.shields.io/badge/TMDb-API%20v3-01d277?style=flat-square&logo=themoviedatabase&logoColor=white" alt="TMDb"/>
  <img src="https://img.shields.io/badge/Gemini-AI-4285f4?style=flat-square&logo=google&logoColor=white" alt="Gemini"/>
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License"/>
</p>

<p align="center">
  Telegram-бот, который мониторит публичные каналы о кино, извлекает названия фильмов и сериалов<br/>
  (из текста, bold-разметки или изображений через Gemini Vision), ищет в TMDb и публикует<br/>
  в целевой канал с рейтингами, ссылками и кнопкой Grab для Radarr/Sonarr.
</p>

---

## Возможности

- **Мониторинг каналов** — Userbot слушает source-каналы и автоматически обрабатывает посты
- **LLM-извлечение** — Gemini извлекает названия из текста (русский → английский, склонения)
- **OCR из изображений** — Gemini Vision распознаёт фильмы по постерам и кадрам (текст + фото одним запросом)
- **Regex-fallback** — кавычки (`«»`, `""`, `„"`) и bold-разметка, если LLM недоступен
- **TMDb + OMDb** — поиск с контекстом (год, режиссёр), рейтинги IMDb/RT/Metacritic
- **Radarr/Sonarr** — кнопка Grab добавляет фильм/сериал в медиасервер
- **DM-интерфейс** — прямые сообщения боту: текст, пересылка, фото → поиск
- **Админ-панель** — `/settings` с inline-кнопками: LLM, auto-post, пользователи, каналы
- **Конфигурируемые модели** — отдельные цепочки моделей для каналов и DM через env
- **Персистентные настройки** — `settings.json`, сохраняются между перезапусками
- **Тихий режим** — неавторизованные пользователи молча игнорируются

## Структура проекта

```
config.py        — загрузка конфигурации из .env
bot_settings.py  — персистентные runtime-настройки (JSON)
extractor.py     — извлечение названий из текста/entities/изображений
llm_client.py    — Gemini LLM/Vision провайдер с ротацией моделей
tmdb_client.py   — поиск по TMDb API с контекстом
omdb_client.py   — рейтинги из OMDb (IMDb, RT, Metacritic)
arr_client.py    — интеграция с Radarr/Sonarr
formatter.py     — форматирование HTML-сообщений и inline-кнопок
main.py          — точка входа, хэндлеры, settings-меню
```

## Установка

```bash
git clone https://github.com/nlkolay/cine-bot.git
cd cine-bot
pip install -r requirements.txt
cp .env.example .env
```

## Настройка

Заполните `.env` файл:

| Переменная | Описание | Обязательная |
|---|---|---|
| `API_ID`, `API_HASH` | [my.telegram.org](https://my.telegram.org) → API development tools | да |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | да |
| `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) | да |
| `TARGET_CHANNEL` | Username (без `@`) или числовой ID канала | да |
| `SOURCE_CHANNELS` | Каналы через запятую (без `@`) | да |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/apikey) | нет |
| `GEMINI_MODEL` | Модель Gemini (по умолчанию `gemini-2.0-flash`) | нет |
| `CHANNEL_MODELS` | Цепочка моделей для каналов (по умолчанию `gemini-3-pro-preview`) | нет |
| `DM_MODELS` | Цепочка моделей для DM (по умолчанию `gemini-3-pro-preview`) | нет |
| `OMDB_API_KEY` | [omdbapi.com](https://www.omdbapi.com/apikey.aspx) | нет |
| `RADARR_URL` | URL Radarr (например `http://localhost:7878`) | нет |
| `RADARR_API_KEY` | API-ключ Radarr | нет |
| `SONARR_URL` | URL Sonarr (например `http://localhost:8989`) | нет |
| `SONARR_API_KEY` | API-ключ Sonarr | нет |
| `ALLOWED_USERS` | ID пользователей через запятую (пусто = все) | нет |
| `ADMIN_USERS` | ID админов через запятую (по умолчанию = `ALLOWED_USERS`) | нет |

Бот должен быть добавлен **администратором** в целевой канал.

## Запуск

```bash
python main.py
```

При первом запуске Telethon запросит код авторизации для userbot-сессии.

### Docker

```bash
docker compose build
docker compose up -d
```

Сессии хранятся в `./sessions/` (volume mount → `/data` внутри контейнера).
При первом запуске: положить код авторизации в `./sessions/auth_code.txt`.

## Зависимости

- [Telethon](https://github.com/LonamiWebs/Telethon) — Telegram MTProto клиент
- [aiohttp](https://github.com/aio-libs/aiohttp) — HTTP-запросы к TMDb/OMDb API
- [google-genai](https://github.com/googleapis/python-genai) — Gemini LLM/Vision SDK
- [pymorphy3](https://github.com/no-one-knows/pymorphy3) — нормализация русских склонений
- [python-dotenv](https://github.com/theskumar/python-dotenv) — загрузка `.env`
