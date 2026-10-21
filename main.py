#main.py - Telegram bot and userbot for TMDb title extraction and posting
import asyncio
import logging
import os

from telethon import TelegramClient, events
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import (
    BotCommand, BotCommandScopeDefault, BotCommandScopePeer,
    InputPeerUser, KeyboardButtonCallback,
)

import config
from bot_settings import Settings
from extractor import TitleContext, extract_titles_smart
from llm_client import GeminiProvider
from arr_client import add_to_radarr, add_to_sonarr
from tmdb_client import MediaResult, search
from formatter import format_result, build_buttons

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SESSION_DIR = config.SESSION_DIR

userbot = TelegramClient(os.path.join(SESSION_DIR, "userbot"), config.API_ID, config.API_HASH)
bot = TelegramClient(os.path.join(SESSION_DIR, "bot"), config.API_ID, config.API_HASH)

settings = Settings(os.path.join(SESSION_DIR, "settings.json"))

llm = GeminiProvider(config.GEMINI_API_KEY, config.GEMINI_MODEL) if config.GEMINI_API_KEY else None
if llm:
    log.info("LLM extraction enabled (model=%s)", config.GEMINI_MODEL)

START_TEXT = (
    "Send or forward a message with movie/series titles — "
    "I'll find them on TMDb.\n\n"
    "You can also send a photo (poster/still) and I'll identify the movie."
)

# Admin state: user_id -> "add_user" | "add_channel"
_admin_state: dict[int, str] = {}


def _is_allowed(user_id: int) -> bool:
    if _is_admin(user_id):
        return True
    allowed = settings.get("allowed_users")
    return not allowed or user_id in allowed


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_USERS


def _get_llm():
    """Return LLM provider if enabled in settings."""
    if llm and settings.get("llm_enabled"):
        return llm
    return None


async def _download_photo(client, message) -> bytes | None:
    """Download photo from message, return bytes or None."""
    if not message.photo:
        return None
    try:
        return await client.download_media(message, bytes)
    except Exception:
        log.exception("Failed to download photo")
        return None


async def _download_album_photos(client, messages) -> list[bytes]:
    """Download all photos from album messages."""
    photos = []
    for msg in messages:
        data = await _download_photo(client, msg)
        if data:
            photos.append(data)
    return photos


async def _extract_with_ocr(
    message, client, *, source: str = "dm",
) -> list[TitleContext]:
    """Extract titles from message: text + photo sent together in one LLM call."""
    active_llm = _get_llm()
    photo = await _download_photo(client, message)
    imgs = [photo] if photo else None
    return await extract_titles_smart(message, active_llm, images=imgs, source=source)


async def _extract_album_with_ocr(
    messages, client, *, source: str = "dm",
) -> list[TitleContext]:
    """Extract titles from album: text + all photos in one LLM call."""
    active_llm = _get_llm()
    text_msg = messages[0]
    photos = await _download_album_photos(client, messages)
    return await extract_titles_smart(text_msg, active_llm, images=photos or None, source=source)



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
# Settings menu
# ---------------------------------------------------------------------------

def _settings_keyboard():
    """Build the main settings menu keyboard."""
    llm_on = settings.get("llm_enabled")
    auto = settings.get("auto_post")
    users = settings.get("allowed_users")
    channels = settings.get("source_channels")

    llm_label = f"{'✅' if llm_on else '❌'} LLM extraction"
    auto_label = f"{'✅' if auto else '❌'} Auto-post forwards"
    users_label = f"\U0001f465 Users ({len(users)})"
    channels_label = f"\U0001f4e1 Channels ({len(channels)})"

    return [
        [KeyboardButtonCallback(text=llm_label, data=b"settings:llm")],
        [KeyboardButtonCallback(text=auto_label, data=b"settings:auto_post")],
        [KeyboardButtonCallback(text=users_label, data=b"settings:users")],
        [KeyboardButtonCallback(text=channels_label, data=b"settings:channels")],
    ]


def _users_keyboard():
    """Build the users sub-menu keyboard."""
    users = settings.get("allowed_users")
    rows = []
    for uid in users:
        rows.append([KeyboardButtonCallback(
            text=f"{uid} \u2715",
            data=f"settings:rm_user:{uid}".encode(),
        )])
    rows.append([KeyboardButtonCallback(text="\u2795 Add user", data=b"settings:add_user")])
    rows.append([KeyboardButtonCallback(text="\u2b05\ufe0f Back", data=b"settings:back")])
    return rows


def _channels_keyboard():
    """Build the channels sub-menu keyboard."""
    channels = settings.get("source_channels")
    rows = []
    for ch in channels:
        rows.append([KeyboardButtonCallback(
            text=f"{ch} \u2715",
            data=f"settings:rm_channel:{ch}".encode(),
        )])
    rows.append([KeyboardButtonCallback(text="\u2795 Add channel", data=b"settings:add_channel")])
    rows.append([KeyboardButtonCallback(text="\u2b05\ufe0f Back", data=b"settings:back")])
    return rows


# ---------------------------------------------------------------------------
# Source channel handlers (dynamic — no chats= filter)
# ---------------------------------------------------------------------------

@userbot.on(events.Album())
async def on_channel_album(event):
    """Handle album posts from source channels."""
    if event.is_private:
        return
    # Skip target channel to avoid processing our own posts
    if event.chat_id == config.TARGET_CHANNEL:
        return
    chat = await event.get_chat()
    username = getattr(chat, "username", None) or ""
    if username not in settings.get("source_channels"):
        return

    text = _get_album_text(event.messages)
    if not text and not any(m.photo for m in event.messages):
        return

    titles = await _extract_album_with_ocr(
        event.messages, userbot,
        source="channel",
    )
    if not titles:
        return

    log.info("Channel album, titles: %s", titles)

    if not settings.get("auto_post"):
        return

    results = await _process_titles(titles)
    if not results:
        return

    await userbot.forward_messages(config.TARGET_CHANNEL, event.messages)
    await asyncio.sleep(1)
    await _post_results_to_channel(results)
    log.info("Sent %d result(s) to %s (album)", len(results), config.TARGET_CHANNEL)


@userbot.on(events.NewMessage())
async def on_new_post(event):
    if event.is_private:
        return
    if event.message.grouped_id:
        return
    # Skip target channel to avoid processing our own posts
    if event.chat_id == config.TARGET_CHANNEL:
        return
    chat = await event.get_chat()
    username = getattr(chat, "username", None) or ""
    if username not in settings.get("source_channels"):
        return

    titles = await _extract_with_ocr(
        event.message, userbot,
        source="channel",
    )
    if not titles:
        return

    log.info("Extracted titles: %s", titles)

    if not settings.get("auto_post"):
        return

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
    if not _is_allowed(event.sender_id):
        return
    await event.respond(START_TEXT)


@bot.on(events.NewMessage(pattern="/settings", func=lambda e: e.is_private))
async def on_settings(event):
    if not _is_admin(event.sender_id):
        return
    await event.respond("Settings:", buttons=_settings_keyboard())



@bot.on(events.NewMessage(pattern="/llm", func=lambda e: e.is_private))
async def on_llm_cmd(event):
    if not _is_admin(event.sender_id):
        return
    new_val = settings.toggle("llm_enabled")
    await event.respond(f"LLM: {'on' if new_val else 'off'}")


@bot.on(events.NewMessage(pattern="/autopost", func=lambda e: e.is_private))
async def on_autopost_cmd(event):
    if not _is_admin(event.sender_id):
        return
    new_val = settings.toggle("auto_post")
    await event.respond(f"Auto-post: {'on' if new_val else 'off'}")


@bot.on(events.NewMessage(pattern="/users", func=lambda e: e.is_private))
async def on_users_cmd(event):
    if not _is_admin(event.sender_id):
        return
    await event.respond("Users:", buttons=_users_keyboard())


@bot.on(events.NewMessage(pattern="/channels", func=lambda e: e.is_private))
async def on_channels_cmd(event):
    if not _is_admin(event.sender_id):
        return
    await event.respond("Channels:", buttons=_channels_keyboard())



@bot.on(events.Album(func=lambda e: e.is_private))
async def on_dm_album(event):
    """Handle forwarded albums in DM."""
    if not _is_allowed(event.messages[0].sender_id):
        return

    is_forward = event.messages[0].fwd_from is not None
    text = _get_album_text(event.messages)
    has_photo = any(m.photo for m in event.messages)

    if not text and not has_photo:
        return

    titles = await _extract_album_with_ocr(
        event.messages, bot,
    )
    if not titles:
        return

    log.info("DM album from user %d, titles: %s (forward=%s)",
             event.messages[0].sender_id, titles, is_forward)

    results = await _process_titles(titles)
    if not results:
        await event.reply("Nothing found on TMDb for the extracted titles.")
        return

    if is_forward and settings.get("auto_post"):
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

    # Handle admin state first (add_user / add_channel text input)
    if event.sender_id in _admin_state:
        if not _is_admin(event.sender_id):
            _admin_state.pop(event.sender_id, None)
        else:
            state = _admin_state.pop(event.sender_id)
            value = event.raw_text.strip()
            if state == "add_user":
                try:
                    uid = int(value)
                    settings.add_to_list("allowed_users", uid)
                    await event.respond(f"Added user {uid}.", buttons=_users_keyboard())
                except ValueError:
                    await event.respond("Invalid user ID. Send a numeric ID.")
            elif state == "add_channel":
                ch = value.lstrip("@").strip()
                if ch:
                    settings.add_to_list("source_channels", ch)
                    await event.respond(f"Added channel {ch}.", buttons=_channels_keyboard())
                else:
                    await event.respond("Invalid channel username.")
            return

    if not _is_allowed(event.sender_id):
        return

    is_forward = event.message.fwd_from is not None

    titles = await _extract_with_ocr(
        event.message, bot,
    )

    # If no titles extracted
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
        elif event.message.photo:
            log.info("DM from user %d: photo sent but OCR returned nothing", event.sender_id)
            await event.respond("Couldn't identify a movie from this image.")
            return
        else:
            # Ignore stickers, GIFs, voice, etc. silently
            if event.message.media:
                return
            await event.respond("Send me a movie or series title to search.")
            return

    log.info("DM from user %d, titles: %s (forward=%s)", event.sender_id, titles, is_forward)

    results = await _process_titles(titles)
    if not results:
        await event.respond("Nothing found on TMDb for the extracted titles.")
        return

    if is_forward and settings.get("auto_post"):
        await bot.forward_messages(config.TARGET_CHANNEL, event.message)
        await asyncio.sleep(1)
        await _post_results_to_channel(results)
        await event.respond(f"Posted {len(results)} result(s) to the channel.")
        log.info("DM forward: posted %d result(s) to %s", len(results), config.TARGET_CHANNEL)
    else:
        await _send_results_to_dm(results, event)
        log.info("DM: sent %d result(s) to user %d", len(results), event.sender_id)


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

@bot.on(events.CallbackQuery(pattern=b"settings:"))
async def on_settings_callback(event):
    if not _is_admin(event.sender_id):
        await event.answer("Access denied.")
        return

    data = event.data.decode()
    action = data.removeprefix("settings:")

    if action == "open":
        await event.answer()
        await event.edit("Settings:", buttons=_settings_keyboard())

    elif action == "llm":
        new_val = settings.toggle("llm_enabled")
        await event.answer(f"LLM: {'on' if new_val else 'off'}")
        await event.edit("Settings:", buttons=_settings_keyboard())

    elif action == "auto_post":
        new_val = settings.toggle("auto_post")
        await event.answer(f"Auto-post: {'on' if new_val else 'off'}")
        await event.edit("Settings:", buttons=_settings_keyboard())

    elif action == "users":
        await event.answer()
        await event.edit("Users:", buttons=_users_keyboard())

    elif action == "channels":
        await event.answer()
        await event.edit("Channels:", buttons=_channels_keyboard())

    elif action == "add_user":
        _admin_state[event.sender_id] = "add_user"
        await event.answer("Send user ID")
        await event.respond("Send the user ID to add:")

    elif action == "add_channel":
        _admin_state[event.sender_id] = "add_channel"
        await event.answer("Send channel username")
        await event.respond("Send the channel username to add:")

    elif action.startswith("rm_user:"):
        uid = int(action.removeprefix("rm_user:"))
        settings.remove_from_list("allowed_users", uid)
        await event.answer(f"Removed {uid}")
        await event.edit("Users:", buttons=_users_keyboard())

    elif action.startswith("rm_channel:"):
        ch = action.removeprefix("rm_channel:")
        settings.remove_from_list("source_channels", ch)
        await event.answer(f"Removed {ch}")
        await event.edit("Channels:", buttons=_channels_keyboard())

    elif action == "back":
        await event.answer()
        await event.edit("Settings:", buttons=_settings_keyboard())


@bot.on(events.CallbackQuery(pattern=b"grab:"))
async def on_grab(event):
    if not _is_allowed(event.sender_id):
        await event.answer("Access denied.")
        return

    parts = event.data.decode().split(":")
    # grab:{media_type}:{tmdb_id}:{tvdb_id}
    if len(parts) != 4:
        await event.answer("Invalid callback data")
        return

    _, media_type, tmdb_id_str, tvdb_id_str = parts

    await event.answer()

    msg = await event.get_message()
    title = ""
    if msg and msg.raw_text:
        first_line = msg.raw_text.split("\n")[0]
        first_line = first_line.lstrip("\U0001f3ac ").strip()
        if first_line.endswith(")") and "(" in first_line:
            first_line = first_line[:first_line.rfind("(")].strip()
        title = first_line

    if media_type == "movie":
        result = await add_to_radarr(int(tmdb_id_str), title)
    else:
        tvdb_id = int(tvdb_id_str)
        if not tvdb_id:
            await event.respond("No TVDB ID available")
            return
        result = await add_to_sonarr(tvdb_id, title)

    await event.respond(result)


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
    # Seed settings from env vars on first run
    settings.seed_defaults(config.ALLOWED_USERS, config.SOURCE_CHANNELS)

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

    log.info("Listening to channels: %s", settings.get("source_channels"))
    log.info("Posting to: %s", config.TARGET_CHANNEL)
    allowed = settings.get("allowed_users")
    if allowed:
        log.info("DM access restricted to: %s", allowed)
    else:
        log.info("DM access: open to everyone")
    log.info("Admin users: %s", config.ADMIN_USERS)
    log.info("LLM: %s, Auto-post: %s",
             settings.get("llm_enabled"), settings.get("auto_post"))

    # Default scope: no commands for regular users
    await bot(SetBotCommandsRequest(
        scope=BotCommandScopeDefault(),
        lang_code="",
        commands=[],
    ))

    # Admin commands: settings menu (per admin user)
    admin_commands = [
        BotCommand(command="settings", description="All settings"),
        BotCommand(command="llm", description="Toggle LLM extraction"),
        BotCommand(command="autopost", description="Toggle auto-post"),
        BotCommand(command="users", description="Manage users"),
        BotCommand(command="channels", description="Manage channels"),
    ]
    for admin_id in config.ADMIN_USERS:
        try:
            peer = await bot.get_input_entity(admin_id)
            await bot(SetBotCommandsRequest(
                scope=BotCommandScopePeer(peer=peer),
                lang_code="",
                commands=admin_commands,
            ))
        except Exception:
            log.warning("Could not set admin commands for user %d", admin_id)
    log.info("Bot commands registered")

    await asyncio.gather(userbot.run_until_disconnected(), bot.run_until_disconnected())


if __name__ == "__main__":
    asyncio.run(main())
