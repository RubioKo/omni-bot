import asyncio
import httpx
import html
import io
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import discord

from ..config import config
from ..services import database as db

logger = logging.getLogger("OmniBot.memes")

_meme_selection_lock = asyncio.Lock()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OmniBot/2.0; community meme fetcher)"}

MIN_UPVOTES = 100
TOP_LIMIT = 25
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
RSS_IMAGE_RE = re.compile(
    r"https://(?:i\.redd\.it|preview\.redd\.it|i\.imgur\.com)[^\s\"<>)]+"
)

FALLBACK_SUBREDDITS = [
    "memes",
    "dankmemes",
]

THEME_POOLS = {
    "gaming": ["gaming", "gamingmemes", "dankmemes"],
    "dark": ["dankmemes", "memes", "me_irl"],
    "futbol": ["soccermemes", "memes", "gaming"],
}

FUNNY_EMOJIS = {"😂", "🤣", "😹", "🔥", "💀", "😭", "💯", "😆"}

SOURCE_LABELS = {}

MEME_EPOCH = datetime(2026, 8, 1, tzinfo=timezone.utc)

_token_cache = {"token": None, "expires_at": 0.0}


def get_subreddit_pool(theme: str | None = None) -> list:
    if theme and theme in THEME_POOLS:
        return list(THEME_POOLS[theme])
    raw = config.meme_subreddits or ""
    subs = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return subs or [
        "memes", "dankmemes", "me_irl", "gaming",
    ]


def get_theme_for_weekday(weekday: int) -> str | None:
    for part in (config.meme_theme_days or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        day_str, theme = part.split(":", 1)
        if day_str.isdigit() and int(day_str) == weekday:
            return theme.strip() or None
    return None


def _parse_reddit_posts(data) -> list:
    posts = []
    if not isinstance(data, dict):
        return posts
    inner = data.get("data")
    if isinstance(inner, list):
        items = inner
    elif isinstance(inner, dict):
        items = [c.get("data") for c in inner.get("children", []) if isinstance(c, dict)]
    else:
        return posts
    for p in items:
        if not isinstance(p, dict) or not p:
            continue
        posts.append({
            "title": p.get("title", ""),
            "url": p.get("url_overridden_by_dest") or p.get("url", ""),
            "permalink": "https://www.reddit.com" + (p.get("permalink") or ""),
            "ups": int(p.get("ups") or p.get("score") or 0),
            "over_18": bool(p.get("over_18", False)),
            "post_hint": p.get("post_hint", ""),
            "is_video": bool(p.get("is_video", False)),
            "is_gallery": bool(p.get("is_gallery", False)),
            "subreddit": p.get("subreddit", ""),
        })
    return posts


def _filter_quality(posts: list, min_upvotes: int = MIN_UPVOTES) -> list:
    good = []
    for p in posts:
        if not p["url"] or not p["title"]:
            continue
        if p["over_18"] or p["is_gallery"]:
            continue

        lower_url = p["url"].lower()
        is_video = lower_url.split("?")[0].endswith(".mp4") and "v.redd.it" not in lower_url
        if is_video:
            good.append({**p, "is_video": True})
            continue

        if p["is_video"]:
            continue
        if p["ups"] < min_upvotes:
            continue
        is_direct_image = lower_url.split("?")[0].endswith(IMAGE_EXTENSIONS)
        if not is_direct_image and p["post_hint"] != "image":
            continue
        good.append({**p, "is_video": False})
    return good


def _next_index(current: int, count: int) -> int:
    if count <= 0:
        return 0
    return (current + 1) % count


async def _get_reddit_token(client: httpx.AsyncClient) -> str | None:
    if not config.reddit_client_id or not config.reddit_client_secret:
        return None

    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    try:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(config.reddit_client_id, config.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers=HEADERS,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        if not token:
            logger.warning("Reddit OAuth: no access_token in response")
            return None
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 60
        logger.info("Reddit OAuth token refreshed")
        return token
    except Exception as e:
        logger.warning(f"Reddit OAuth error: {e}")
        return None


async def _fetch_reddit_top(subreddit: str) -> list:
    url = f"https://oauth.reddit.com/r/{subreddit}/top?t=day&limit={TOP_LIMIT}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            token = await _get_reddit_token(client)
            if not token:
                return []
            headers = {**HEADERS, "Authorization": f"Bearer {token}"}
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"Reddit API error ({subreddit}): {e}")
        return []
    return _parse_reddit_posts(data)


def _parse_rss_entries(xml_text: str) -> list:
    posts = []
    if not xml_text or not xml_text.strip():
        return posts
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"RSS parse error: {e}")
        return posts

    for entry in root.findall("a:entry", ATOM_NS):
        title = (entry.findtext("a:title", "", ATOM_NS) or "").strip()
        link_el = entry.find("a:link", ATOM_NS)
        permalink = link_el.get("href", "") if link_el is not None else ""
        content = entry.findtext("a:content", "", ATOM_NS) or ""
        categories = [
            c.get("term", "").lower()
            for c in entry.findall("a:category", ATOM_NS)
        ]
        images = [html.unescape(u) for u in RSS_IMAGE_RE.findall(content)]

        if not title or not images:
            continue
        if "nsfw" in categories:
            continue

        posts.append({
            "title": title,
            "url": images[0],
            "permalink": permalink,
            "ups": 0,
            "subreddit": categories[0] if categories else "",
        })
    return posts


async def _fetch_reddit_rss(subreddit: str) -> tuple[list, bool]:
    url = f"https://www.reddit.com/r/{subreddit}/top.rss?t=day&limit={TOP_LIMIT}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers=HEADERS)
            if r.status_code == 429:
                logger.warning("Reddit RSS rate limited (429), skipping RSS stage")
                return [], True
            r.raise_for_status()
            posts = _parse_rss_entries(r.text)
    except Exception as e:
        logger.warning(f"Reddit RSS error ({subreddit}): {e}")
        return [], False
    return posts, False


async def _fetch_from_meme_api(subreddit: str) -> dict | None:
    url = f"https://meme-api.com/gimme/{subreddit}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=HEADERS)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"Meme API error ({subreddit}): {e}")
        return None

    if data.get("nsfw", True):
        return None
    raw_url = data.get("url", "")
    if not raw_url:
        return None

    url = html.unescape(raw_url).split("?")[0]
    lower_url = url.lower()
    is_video = lower_url.endswith(".mp4") and "v.redd.it" not in lower_url
    is_image = lower_url.endswith(IMAGE_EXTENSIONS)
    if not is_video and not is_image:
        logger.info(f"Meme API returned non-media URL, skipping: {raw_url[:80]}")
        return None

    return {
        "title": data.get("title", "Sin titulo"),
        "url": raw_url,
        "upvotes": data.get("ups", 0),
        "permalink": data.get("postLink", ""),
        "subreddit": data.get("subreddit", subreddit),
        "is_video": is_video,
    }


async def get_daily_meme(theme: str | None = None) -> dict | None:
    pool = get_subreddit_pool(theme)

    try:
        stored = await db.get_setting("meme_sub_index")
        start_idx = int(stored) if stored and stored.isdigit() else 0
    except Exception:
        start_idx = 0
    start_idx = start_idx % len(pool) if pool else 0

    weights = await db.get_source_weights()
    if weights:
        shuffled = list(pool)
        random.shuffle(shuffled)
        pool = sorted(shuffled, key=lambda s: -(min(weights.get(s, 0), 10) + 1))

    async def _record_and_return(post: dict, idx: int) -> dict | None:
        meme = {
            "title": post["title"],
            "url": post["url"],
            "permalink": post.get("permalink", ""),
            "subreddit": post.get("subreddit", ""),
            "upvotes": int(post.get("ups") or post.get("upvotes") or 0),
            "is_video": bool(post.get("is_video", False)),
        }
        async with _meme_selection_lock:
            seen = await db.is_meme_seen(meme["url"])
            if seen:
                return None
            await db.add_meme_history(meme["url"], meme["title"])
            await db.set_setting("meme_sub_index", str(_next_index(idx, len(pool))))
        logger.info(
            f"Meme ({meme['subreddit']}): {meme['title'][:60]} "
            f"({meme['upvotes']} ups)"
        )
        return meme

    has_oauth = bool(config.reddit_client_id and config.reddit_client_secret)

    if has_oauth:
        for offset in range(len(pool)):
            idx = (start_idx + offset) % len(pool)
            sub = pool[idx]
            posts = await _fetch_reddit_top(sub)
            candidates = _filter_quality(posts)
            if not candidates:
                continue
            random.shuffle(candidates)
            for post in candidates:
                meme = await _record_and_return(post, idx)
                if meme:
                    return meme

    for offset in range(len(pool)):
        idx = (start_idx + offset) % len(pool)
        posts, rate_limited = await _fetch_reddit_rss(pool[idx])
        if rate_limited:
            break
        if not posts:
            continue
        random.shuffle(posts)
        for post in posts:
            meme = await _record_and_return(post, idx)
            if meme:
                return meme

    for offset in range(len(pool)):
        idx = (start_idx + offset) % len(pool)
        meme = await _fetch_from_meme_api(pool[idx])
        if meme:
            result = await _record_and_return(meme, idx)
            if result:
                return result

    for sub in FALLBACK_SUBREDDITS:
        meme = await _fetch_from_meme_api(sub)
        if not meme:
            continue
        result = await _record_and_return(meme, start_idx)
        if result:
            logger.info(f"Meme (EN fallback): {result['title'][:60]} from r/{sub}")
            return result

    return None


async def get_memes(count: int = 1, theme: str | None = None) -> list:
    count = min(max(int(count), 1), 3)
    memes = []
    for _ in range(count):
        meme = await get_daily_meme(theme)
        if not meme:
            break
        memes.append(meme)
    return memes


def get_day_index() -> int:
    return (datetime.now(timezone.utc) - MEME_EPOCH).days + 1


def build_meme_embed(meme: dict, day_index: int | None = None) -> discord.Embed:
    ups = int(meme.get("upvotes") or 0)
    ups_text = f" · 🔼 {ups:,}" if ups > 0 else " · 🔥 Top del día"
    source = meme.get("subreddit", "")
    source_text = SOURCE_LABELS.get(source, f"r/{source}")
    footer = f"{source_text}{ups_text}"
    if day_index is not None:
        footer += f" · #{day_index}"

    embed = discord.Embed(
        title="🤣 MEME DEL DIA",
        description=meme["title"],
        color=0xFF4500,
        url=meme.get("permalink") or None,
    )
    embed.set_image(url=meme["url"])
    embed.set_footer(text=footer)
    return embed


class MemeRerollView(discord.ui.View):
    _rolls: dict = {}
    MAX_ROLLS_PER_HOUR = 3

    def __init__(self):
        super().__init__(timeout=None)

    @classmethod
    def _can_reroll(cls, user_id: int) -> tuple[bool, int]:
        now = time.time()
        rolls = [t for t in cls._rolls.get(user_id, []) if now - t < 3600]
        cls._rolls[user_id] = rolls
        if len(rolls) >= cls.MAX_ROLLS_PER_HOUR:
            return False, 0
        cls._rolls[user_id] = rolls + [now]
        return True, cls.MAX_ROLLS_PER_HOUR - len(rolls) - 1

    @discord.ui.button(
        label="🔄 Otro meme",
        style=discord.ButtonStyle.secondary,
        custom_id="meme_reroll",
    )
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        try:
            allowed, remaining = self._can_reroll(interaction.user.id)
            if not allowed:
                await interaction.followup.send(
                    f"⏳ Ya usaste tus {self.MAX_ROLLS_PER_HOUR} rerolls de esta hora.",
                    ephemeral=True,
                )
                return

            weekday_theme = get_theme_for_weekday(datetime.now().weekday())
            meme = await get_daily_meme(weekday_theme)
            if not meme:
                await interaction.followup.send(
                    "No hay más memes frescos ahora. Volvé más tarde.",
                    ephemeral=True,
                )
                return

            await send_meme_followup(interaction, meme)
            if remaining > 0:
                await interaction.followup.send(
                    f"Te quedan {remaining} rerolls esta hora.", ephemeral=True
                )
        except Exception as e:
            logger.error(f"Reroll error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Ocurrió un error al buscar otro meme. Intentá de nuevo.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass


async def _download_image(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers=HEADERS)
            r.raise_for_status()
            if len(r.content) > 15 * 1024 * 1024:
                logger.warning(f"Image too large to re-upload: {url[:80]}")
                return None
            return r.content
    except Exception as e:
        logger.warning(f"Image download failed: {url[:80]} - {e}")
        return None


WESERV_URL = "https://wsrv.nl/?url={}"

DIRECT_EMBED_DOMAINS = {"i.redd.it", "i.imgur.com", "cdn.discordapp.com", "media.discordapp.net"}


def _needs_download(url: str) -> bool:
    """True si el host NO es de confianza para el proxy de imágenes de Discord."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return True
    if not host:
        return True
    return not any(host == d or host.endswith("." + d) for d in DIRECT_EMBED_DOMAINS)


async def prepare_memes(memes: list) -> tuple[list, list]:
    """Prepara embeds y archivos. Todo host fuera de la whitelist se
    descarga y re-sube como attachment (cadena: attachment → wsrv proxy
    → URL original), garantizando que Discord renderice la imagen."""
    embeds = []
    files = []
    for meme in memes:
        url = html.unescape(meme["url"])
        embed = build_meme_embed({**meme, "url": url}, get_day_index())
        if _needs_download(url):
            data = await _download_image(url)
            if data:
                filename = f"meme_{len(files)}.jpg"
                embed.set_image(url=f"attachment://{filename}")
                files.append(discord.File(io.BytesIO(data), filename=filename))
                logger.info(f"Meme image attached (download): {url[:80]}")
            else:
                embed.set_image(url=WESERV_URL.format(url))
                logger.info(f"Using wsrv proxy for: {url[:80]}")
        else:
            logger.info(f"Direct embed (trusted host): {url[:80]}")
        embeds.append(embed)
    return embeds, files


def _looks_like_media(url: str) -> bool:
    lower = html.unescape(url).lower().split("?")[0]
    return lower.endswith(IMAGE_EXTENSIONS) or (
        lower.endswith(".mp4") and "v.redd.it" not in lower
    )


async def send_meme_followup(interaction: discord.Interaction, meme: dict):
    view = MemeRerollView()
    if meme.get("is_video") or not _looks_like_media(meme["url"]):
        await interaction.followup.send(
            content=f"🎬 **{meme['title']}**\n{meme['url']}",
            view=view,
        )
        return
    embeds, files = await prepare_memes([meme])
    kwargs = {"embeds": embeds, "view": view}
    if files:
        kwargs["files"] = files
    await interaction.followup.send(**kwargs)


async def send_meme(channel: discord.TextChannel, meme: dict, view: discord.ui.View | None = None):
    if meme.get("is_video") or not _looks_like_media(meme["url"]):
        return await channel.send(
            content=f"🎬 **{meme['title']}**\n{meme['url']}",
            view=view,
        )
    embeds, files = await prepare_memes([meme])
    kwargs = {"embeds": embeds, "view": view}
    if files:
        kwargs["files"] = files
    return await channel.send(**kwargs)
