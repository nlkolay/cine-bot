import asyncio
import logging
import os

from telethon import TelegramClient, events

import config
from extractor import TitleContext, extract_titles, extract_titles_smart
from llm_client import GeminiProvider
from tmdb_client import MediaResult, search
from formatter import format_result, build_buttons

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SESSION_DIR = os.environ.get("SESSION_DIR", ".")

userbot = TelegramClient(os.path.join(SESSION_DIR, "userbot"), config.API_ID, config.API_HASH)
bot = TelegramClient(os.path.join(SESSION_DIR, "bot"), config.API_ID, config.API_HASH)

llm = GeminiProvider(config.GEMINI_API_KEY, config.GEMINI_MODEL) if config.GEMINI_API_KEY else None
if llm:
    log.info("LLM extraction enabled (model=%s)", config.GEMINI_MODEL)

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


async def _post_results_to_channel(results: list[MediaResult]):
    """Send result cards to the target channel."""
    for r in results:
        text = format_result(r)
        buttons = build_buttons(r)
        await bot.send_message(
            config.TARGET_CHANNEL, text, parse_mode="html",
            link_preview=False, buttons=buttons,
        )
        await asyncio.sleep(1)


async def _send_results_to_dm(results: list[MediaResult], event):
    """Send results directly back to the user in DM."""
    for r in results:
        text = format_result(r)
        buttons = build_buttons(r)
        await event.respond(text, parse_mode="html", link_preview=False, buttons=buttons)


def _get_album_text(messages) -> str:
    """Get caption text from album messages (usually on the first one)."""
    for msg in messages:
        if msg.raw_text:
            return msg.raw_text
    return ""


# ---------------------------------------------------------------------------
# Source channel handlers
# ---------------------------------------------------------------------------

@userbot.on(events.Album(chats=config.SOURCE_CHANNELS))
async def on_channel_album(event):
    """Handle album posts from source channels."""
    text = _get_album_text(event.messages)
    if not text:
        return

    titles = await extract_titles_smart(event.messages[0], llm)
    if not titles:
        return

    log.info("Channel album, titles: %s", titles)

    results = await _process_titles(titles)
    if not results:
        return

    # Forward entire album, then post results
    await userbot.forward_messages(config.TARGET_CHANNEL, event.messages)
    await asyncio.sleep(1)
    await _post_results_to_channel(results)
    log.info("Sent %d result(s) to %s (album)", len(results), config.TARGET_CHANNEL)


@userbot.on(events.NewMessage(chats=config.SOURCE_CHANNELS))
async def on_new_post(event):
    # Skip grouped messages — handled by on_channel_album
    if event.message.grouped_id:
        return

    titles = await extract_titles_smart(event.message, llm)
    if not titles:
        return

    log.info("Extracted titles: %s", titles)

    results = await _process_titles(titles)
    if not results:
        return

    await userbot.forward_messages(config.TARGET_CHANNEL, event.message)
    await asyncio.sleep(1)
    await _post_results_to_channel(results)
    log.info("Sent %d message(s) to %s", len(results), config.TARGET_CHANNEL)


# ---------------------------------------------------------------------------
# Bot DM handlers
# ---------------------------------------------------------------------------

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


@bot.on(events.Album(func=lambda e: e.is_private))
async def on_dm_album(event):
    """Handle forwarded albums in DM."""
    if not _is_allowed(event.messages[0].sender_id):
        await event.reply("Access denied.")
        return

    is_forward = event.messages[0].fwd_from is not None
    text = _get_album_text(event.messages)
    if not text:
        return

    titles = await extract_titles_smart(event.messages[0], llm)
    if not titles:
        return

    log.info("DM album from user %d, titles: %s (forward=%s)",
             event.messages[0].sender_id, titles, is_forward)

    results = await _process_titles(titles)
    if not results:
        await event.reply("Nothing found on TMDb for the extracted titles.")
        return

    if is_forward:
        await bot.forward_messages(config.TARGET_CHANNEL, event.messages)
        await asyncio.sleep(1)
        await _post_results_to_channel(results)
        await event.reply(f"Posted {len(results)} result(s) to the channel.")
        log.info("DM album forward: posted %d result(s) to %s", len(results), config.TARGET_CHANNEL)
    else:
        await _send_results_to_dm(results, event)
        log.info("DM album: sent %d result(s) to user", len(results))


@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.raw_text.startswith("/")))
async def on_dm(event):
    # Skip grouped messages — handled by on_dm_album
    if event.message.grouped_id:
        return

    if not _is_allowed(event.sender_id):
        await event.respond("Access denied.")
        return

    is_forward = event.message.fwd_from is not None

    titles = await extract_titles_smart(event.message, llm)

    # If no titles extracted, treat as search query
    if not titles:
        query = event.raw_text.strip()
        if query:
            log.info("DM from user %d: direct search for: %s", event.sender_id, query[:120])
            result = await search(TitleContext(title=query))
            if result:
                text = format_result(result)
                buttons = build_buttons(result)
                await event.respond(text, parse_mode="html", link_preview=False, buttons=buttons)
            else:
                await event.respond(f"Nothing found for: {query}")
            return
        else:
            await event.respond("Send me a movie or series title to search.")
            return

    log.info("DM from user %d, titles: %s (forward=%s)", event.sender_id, titles, is_forward)

    results = await _process_titles(titles)
    if not results:
        await event.respond("Nothing found on TMDb for the extracted titles.")
        return

    if is_forward:
        await bot.forward_messages(config.TARGET_CHANNEL, event.message)
        await asyncio.sleep(1)
        await _post_results_to_channel(results)
        await event.respond(f"Posted {len(results)} result(s) to the channel.")
        log.info("DM forward: posted %d result(s) to %s", len(results), config.TARGET_CHANNEL)
    else:
        await _send_results_to_dm(results, event)
        log.info("DM: sent %d result(s) to user %d", len(results), event.sender_id)


# ---------------------------------------------------------------------------
# Auth & startup
# ---------------------------------------------------------------------------

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
