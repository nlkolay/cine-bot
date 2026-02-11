import asyncio
import logging

from telethon import TelegramClient, events

import config
from extractor import extract_titles
from tmdb_client import search
from formatter import format_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

userbot = TelegramClient("userbot", config.API_ID, config.API_HASH)
bot = TelegramClient("bot", config.API_ID, config.API_HASH)


@userbot.on(events.NewMessage(chats=config.SOURCE_CHANNELS))
async def on_new_post(event):
    titles = extract_titles(event.message)
    if not titles:
        return

    log.info("Extracted titles: %s", titles)

    results = []
    for title in titles:
        result = await search(title)
        if result:
            results.append(result)
            log.info("Found: %s (%s)", result.title, result.year)
        else:
            log.warning("Not found on TMDb: %s", title)

    if not results:
        return

    source_text = event.message.raw_text or ""
    text = format_message(results, source_text)
    await bot.send_message(config.TARGET_CHANNEL, text, parse_mode="html", link_preview=False)
    log.info("Sent message to %s", config.TARGET_CHANNEL)


async def main():
    log.info("Starting userbot...")
    await userbot.start()

    log.info("Starting bot...")
    await bot.start(bot_token=config.BOT_TOKEN)

    me = await userbot.get_me()
    log.info("Userbot logged in as %s (id=%d)", me.first_name, me.id)

    bot_me = await bot.get_me()
    log.info("Bot logged in as @%s", bot_me.username)

    log.info("Listening to channels: %s", config.SOURCE_CHANNELS)
    log.info("Posting to: %s", config.TARGET_CHANNEL)

    await asyncio.gather(userbot.run_until_disconnected(), bot.run_until_disconnected())


if __name__ == "__main__":
    asyncio.run(main())
