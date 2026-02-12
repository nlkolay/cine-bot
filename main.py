import asyncio
import logging
import os

from telethon import TelegramClient, events

import config
from extractor import TitleContext, extract_titles
from tmdb_client import MediaResult, search
from formatter import format_result, format_source, build_buttons

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SESSION_DIR = os.environ.get("SESSION_DIR", ".")

userbot = TelegramClient(os.path.join(SESSION_DIR, "userbot"), config.API_ID, config.API_HASH)
bot = TelegramClient(os.path.join(SESSION_DIR, "bot"), config.API_ID, config.API_HASH)

START_TEXT = (
    "Hi! Forward me a message with movie/series titles, "
    "and I'll look them up and post to the channel.\n\n"
    "Or use /search Movie Title to search without publishing."
)


def _is_allowed(user_id: int) -> bool:
    return not config.ALLOWED_USERS or user_id in config.ALLOWED_USERS


async def _process_titles(contexts: list[TitleContext]) -> list[MediaResult]:
    """Search TMDb for each title context, deduplicate by tmdb_id."""
    results: list[MediaResult] = []
    seen: set[int] = set()
    for ctx in contexts:
        log.info(
            "Searching: %r (year=%s, director=%s)",
            ctx.title, ctx.year, ctx.director,
        )
        result = await search(ctx)
        if result:
            if result.tmdb_id in seen:
                log.info("Skipping duplicate: %s (%s)", result.title, result.year)
                continue
            seen.add(result.tmdb_id)
            results.append(result)
            log.info("Found: %s (%s)", result.title, result.year)
        else:
            log.warning("Not found on TMDb: %s", ctx.title)
    return results


async def _send_results(results: list[MediaResult], source_text: str = ""):
    """Send each result as a separate message to the target channel."""
    if source_text.strip():
        await bot.send_message(
            config.TARGET_CHANNEL, format_source(source_text),
            parse_mode="html", link_preview=False,
        )
        await asyncio.sleep(1)
    for r in results:
        text = format_result(r)
        buttons = build_buttons(r)
        await bot.send_message(
            config.TARGET_CHANNEL, text, parse_mode="html",
            link_preview=False, buttons=buttons,
        )
        await asyncio.sleep(1)


@userbot.on(events.NewMessage(chats=config.SOURCE_CHANNELS))
async def on_new_post(event):
    titles = extract_titles(event.message)
    if not titles:
        return

    log.info("Extracted titles: %s", titles)

    results = await _process_titles(titles)
    if not results:
        return

    source_text = event.message.raw_text or ""
    await _send_results(results, source_text)
    log.info("Sent %d message(s) to %s", len(results), config.TARGET_CHANNEL)


@bot.on(events.NewMessage(pattern="/start", func=lambda e: e.is_private))
async def on_start(event):
    await event.respond(START_TEXT)


@bot.on(events.NewMessage(pattern="/search", func=lambda e: e.is_private))
async def on_search(event):
    if not _is_allowed(event.sender_id):
        await event.respond("Access denied.")
        return

    query = event.raw_text.removeprefix("/search").strip()
    if not query:
        await event.respond("Usage: /search Movie Title")
        return

    log.info("/search from user %d: %s", event.sender_id, query)
    result = await search(TitleContext(title=query))
    if not result:
        await event.respond(f"Nothing found for: {query}")
        return

    text = format_result(result)
    buttons = build_buttons(result)
    await event.respond(text, parse_mode="html", link_preview=False, buttons=buttons)


@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.raw_text.startswith("/")))
async def on_dm(event):
    if not _is_allowed(event.sender_id):
        await event.respond("Access denied.")
        return

    titles = extract_titles(event.message)
    
    # If no titles extracted (no quotes), treat the entire message as a search query
    if not titles:
        query = event.raw_text.strip()
        if query:
            log.info("DM from user %d: direct search for: %s", event.sender_id, query[:120])
            result = await search(TitleContext(title=query))
            if result:
                text = format_result(result)
                buttons = build_buttons(result)
                await event.respond(text, parse_mode="html", link_preview=False, buttons=buttons)
                await event.respond(f"Posted to channel: {config.TARGET_CHANNEL}")
            else:
                await event.respond(f"Nothing found for: {query}")
            return
        else:
            await event.respond("Send me a movie or series title to search.")
            return

    log.info("DM from user %d, titles: %s", event.sender_id, titles)

    results = await _process_titles(titles)
    if not results:
        await event.respond("Nothing found on TMDb for the extracted titles.")
        return

    source_text = event.message.raw_text or ""
    await _send_results(results, source_text)
    await event.respond(f"Posted {len(results)} result(s) to the channel.")
    log.info("DM: posted %d result(s) to %s", len(results), config.TARGET_CHANNEL)


CODE_FILE = os.path.join(SESSION_DIR, "auth_code.txt")


async def _wait_for_code():
    """Wait for auth code to appear in auth_code.txt file."""
    log.info("Waiting for Telegram auth code — write it to: %s", os.path.abspath(CODE_FILE))
    while True:
        if os.path.exists(CODE_FILE):
            code = open(CODE_FILE).read().strip()
            if code:
                os.remove(CODE_FILE)
                log.info("Got auth code from file")
                return code
        await asyncio.sleep(1)


async def main():
    log.info("Starting userbot...")
    await userbot.start(
        phone=config.PHONE,
        code_callback=_wait_for_code,
        password=config.TG_PASSWORD or None,
    )

    log.info("Starting bot...")
    await bot.start(bot_token=config.BOT_TOKEN)

    me = await userbot.get_me()
    log.info("Userbot logged in as %s (id=%d)", me.first_name, me.id)

    bot_me = await bot.get_me()
    log.info("Bot logged in as @%s", bot_me.username)

    log.info("Listening to channels: %s", config.SOURCE_CHANNELS)
    log.info("Posting to: %s", config.TARGET_CHANNEL)
    if config.ALLOWED_USERS:
        log.info("DM access restricted to: %s", config.ALLOWED_USERS)
    else:
        log.info("DM access: open to everyone")

    await asyncio.gather(userbot.run_until_disconnected(), bot.run_until_disconnected())


if __name__ == "__main__":
    asyncio.run(main())
