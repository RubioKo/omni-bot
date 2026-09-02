import asyncio
import time

import pytest

from src.services import memes


def make_post(**overrides):
    post = {
        "title": "Un meme gracioso",
        "url": "https://i.redd.it/abc123.jpg",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "ups": 500,
        "over_18": False,
        "post_hint": "image",
        "is_video": False,
        "is_gallery": False,
        "subreddit": "maau",
        "created_utc": time.time(),
    }
    post.update(overrides)
    return post


def make_reddit_response(posts):
    return {"data": {"children": [{"data": p} for p in posts]}}


def make_pullpush_response(posts):
    return {"data": posts}


def test_parse_reddit_posts_basic():
    data = make_reddit_response([make_post()])
    posts = memes._parse_reddit_posts(data)
    assert len(posts) == 1
    assert posts[0]["subreddit"] == "maau"
    assert posts[0]["permalink"].startswith("https://www.reddit.com")


def test_parse_pullpush_format():
    post = make_post()
    post.pop("ups")
    post["score"] = 250
    data = make_pullpush_response([post])
    posts = memes._parse_reddit_posts(data)
    assert len(posts) == 1
    assert posts[0]["ups"] == 250


def test_parse_pullpush_score_fallback():
    data = make_pullpush_response([make_post(ups=0, score=300)])
    posts = memes._parse_reddit_posts(data)
    assert posts[0]["ups"] == 300


def test_parse_reddit_posts_prefers_direct_url():
    data = make_reddit_response([make_post(url="https://i.redd.it/direct.jpg")])
    posts = memes._parse_reddit_posts(data)
    assert posts[0]["url"] == "https://i.redd.it/direct.jpg"


def test_parse_reddit_posts_malformed():
    assert memes._parse_reddit_posts({}) == []
    assert memes._parse_reddit_posts({"data": {"children": [{"nope": 1}]}}) == []
    assert memes._parse_reddit_posts("basura") == []


def test_filter_quality_keeps_good_post():
    posts = [make_post()]
    good = memes._filter_quality(posts, 100)
    assert len(good) == 1


def test_filter_quality_low_upvotes():
    posts = [make_post(ups=50)]
    assert memes._filter_quality(posts, 100) == []


def test_filter_quality_nsfw():
    posts = [make_post(over_18=True)]
    assert memes._filter_quality(posts, 100) == []


def test_filter_quality_video():
    posts = [make_post(is_video=True)]
    assert memes._filter_quality(posts, 100) == []


def test_filter_quality_gallery():
    posts = [make_post(is_gallery=True)]
    assert memes._filter_quality(posts, 100) == []


def test_filter_quality_non_image_url():
    posts = [make_post(url="https://v.redd.it/video.mp4", post_hint="hosted:video")]
    assert memes._filter_quality(posts, 100) == []


def test_filter_quality_no_title():
    posts = [make_post(title="")]
    assert memes._filter_quality(posts, 100) == []


def test_next_index_rotates():
    assert memes._next_index(0, 7) == 1
    assert memes._next_index(6, 7) == 0
    assert memes._next_index(3, 0) == 0


def test_get_reddit_token_no_credentials(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "reddit_client_id", "")
    monkeypatch.setattr(config, "reddit_client_secret", "")
    import httpx

    async def run():
        async with httpx.AsyncClient() as client:
            return await memes._get_reddit_token(client)

    assert asyncio.run(run()) is None


def test_fetch_reddit_top_no_token_returns_empty(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "reddit_client_id", "")
    monkeypatch.setattr(config, "reddit_client_secret", "")

    assert asyncio.run(memes._fetch_reddit_top("maau")) == []


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <category label="r/maau" term="maau"/>
    <content type="html">&lt;table&gt; &lt;tr&gt;&lt;td&gt; &lt;a href="https://i.redd.it/abc123.jpg"&gt;[link]&lt;/a&gt; &lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</content>
    <link href="https://www.reddit.com/r/MAAU/comments/xyz/titulo/"/>
    <title>Un meme chistoso</title>
    <updated>2026-08-23T15:00:00+00:00</updated>
  </entry>
</feed>"""


def test_parse_rss_entries_basic():
    posts = memes._parse_rss_entries(SAMPLE_RSS)
    assert len(posts) == 1
    assert posts[0]["title"] == "Un meme chistoso"
    assert posts[0]["url"] == "https://i.redd.it/abc123.jpg"
    assert posts[0]["subreddit"] == "maau"
    assert posts[0]["ups"] == 0


def test_parse_rss_entries_nsfw_skipped():
    nsfw_rss = SAMPLE_RSS.replace(
        '<category label="r/maau" term="maau"/>',
        '<category label="r/maau" term="maau"/>\n    <category label="nsfw" term="nsfw"/>'
    )
    assert memes._parse_rss_entries(nsfw_rss) == []


def test_parse_rss_entries_no_image_skipped():
    no_img = SAMPLE_RSS.replace("https://i.redd.it/abc123.jpg", "")
    assert memes._parse_rss_entries(no_img) == []


def test_parse_rss_entries_video_skipped():
    video_rss = SAMPLE_RSS.replace("https://i.redd.it/abc123.jpg", "https://v.redd.it/video123")
    assert memes._parse_rss_entries(video_rss) == []


def test_parse_rss_entries_empty():
    assert memes._parse_rss_entries("") == []
    assert memes._parse_rss_entries(None) == []
    assert memes._parse_rss_entries("<html>no es rss</html>") == []


def test_build_meme_embed_with_upvotes():
    meme = {
        "title": "Titulo",
        "url": "https://i.redd.it/x.jpg",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 500,
    }
    embed = memes.build_meme_embed(meme, 42)
    assert "🔼 500" in embed.footer.text
    assert "#42" in embed.footer.text
    assert embed.title == "🤣 MEME DEL DIA"
    assert embed.image.url == "https://i.redd.it/x.jpg"


def test_build_meme_embed_without_upvotes():
    meme = {
        "title": "Titulo",
        "url": "https://i.redd.it/x.jpg",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 0,
    }
    embed = memes.build_meme_embed(meme)
    assert "Top del día" in embed.footer.text
    assert "🔼" not in embed.footer.text
    assert embed.url == "https://www.reddit.com/r/maau/comments/x/"



def test_filter_quality_accepts_direct_mp4():
    post = make_post(url="https://videos.memedroid.com/videos/x.mp4", ups=0, post_hint="")
    good = memes._filter_quality([post], 100)
    assert len(good) == 1
    assert good[0]["is_video"] is True


def test_filter_quality_rejects_vreddit_mp4():
    post = make_post(url="https://v.redd.it/audio-less.mp4", ups=0, post_hint="hosted:video", is_video=True)
    assert memes._filter_quality([post], 100) == []


def test_get_theme_for_weekday(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_theme_days", "0:gaming,2:dark,4:futbol")
    assert memes.get_theme_for_weekday(0) == "gaming"
    assert memes.get_theme_for_weekday(2) == "dark"
    assert memes.get_theme_for_weekday(4) == "futbol"
    assert memes.get_theme_for_weekday(1) is None
    assert memes.get_theme_for_weekday(6) is None


def test_get_theme_for_weekday_malformed(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_theme_days", "basura,x:dark")
    assert memes.get_theme_for_weekday(0) is None


def test_theme_pool_selection(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_subreddits", "")
    pool = memes.get_subreddit_pool("gaming")
    assert pool == memes.THEME_POOLS["gaming"]
    default = memes.get_subreddit_pool(None)
    assert "memes" in default


def test_source_label_in_embed():
    meme = {
        "title": "Titulo",
        "url": "https://i.redd.it/x.jpg",
        "permalink": "https://www.reddit.com/r/memes/comments/x/",
        "subreddit": "memes",
        "upvotes": 0,
    }
    embed = memes.build_meme_embed(meme)
    assert "r/memes" in embed.footer.text


@pytest.mark.asyncio
async def test_prepare_memes_untrusted_host_attachment(monkeypatch):
    async def fake_download(url):
        return b"fake-image-bytes"

    monkeypatch.setattr(memes, "_download_image", fake_download)

    meme = {
        "title": "Titulo",
        "url": "https://statics.memondo.com/x.jpg",
        "permalink": "https://example.com/meme/x",
        "subreddit": "memes",
        "upvotes": 0,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(embeds) == 1
    assert len(files) == 1
    assert embeds[0].image.url.startswith("attachment://")
    assert files[0].fp is not None


@pytest.mark.asyncio
async def test_prepare_memes_untrusted_host_wsrv_fallback(monkeypatch):
    async def fake_download(url):
        return None

    monkeypatch.setattr(memes, "_download_image", fake_download)

    meme = {
        "title": "Titulo",
        "url": "https://statics.memondo.com/x.jpg",
        "permalink": "https://example.com/meme/x",
        "subreddit": "memes",
        "upvotes": 0,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(embeds) == 1
    assert files == []
    assert embeds[0].image.url.startswith("https://wsrv.nl/?url=")
    assert "statics.memondo.com" in embeds[0].image.url


@pytest.mark.asyncio
async def test_prepare_memes_other_sources_no_download():
    meme = {
        "title": "Titulo",
        "url": "https://i.redd.it/abc.jpg",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 100,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(embeds) == 1
    assert files == []
    assert embeds[0].image.url == "https://i.redd.it/abc.jpg"


@pytest.mark.asyncio
async def test_prepare_memes_preview_reddit_downloaded(monkeypatch):
    async def fake_download(url):
        return b"fake-image-bytes"

    monkeypatch.setattr(memes, "_download_image", fake_download)

    meme = {
        "title": "Titulo",
        "url": "https://preview.redd.it/abc.jpg?width=1080&s=sig",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 0,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(files) == 1
    assert embeds[0].image.url.startswith("attachment://")


@pytest.mark.asyncio
async def test_prepare_memes_i_reddit_not_downloaded():
    meme = {
        "title": "Titulo",
        "url": "https://i.redd.it/direct.jpg",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 0,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert files == []
    assert embeds[0].image.url == "https://i.redd.it/direct.jpg"


def test_needs_download():
    assert memes._needs_download("https://preview.redd.it/abc.jpg") is True
    assert memes._needs_download("https://statics.memondo.com/x.jpg") is True
    assert memes._needs_download("https://i.kym-cdn.com/entries/x.jpg") is True
    assert memes._needs_download("https://pbs.twimg.com/media/x.jpg") is True
    assert memes._needs_download("https://i.redd.it/abc.jpg") is False
    assert memes._needs_download("https://i.imgur.com/abc.jpg") is False
    assert memes._needs_download("https://cdn.discordapp.com/attachments/x/y.jpg") is False
    assert memes._needs_download("not a url") is True


@pytest.mark.asyncio
async def test_prepare_memes_unknown_host_downloaded(monkeypatch):
    async def fake_download(url):
        return b"fake-image-bytes"

    monkeypatch.setattr(memes, "_download_image", fake_download)

    meme = {
        "title": "Titulo",
        "url": "https://i.kym-cdn.com/entries/abc.jpg",
        "permalink": "https://knowyourmeme.com/memes/x",
        "subreddit": "memes",
        "upvotes": 50,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(files) == 1
    assert embeds[0].image.url.startswith("attachment://")


@pytest.mark.asyncio
async def test_prepare_memes_discord_cdn_direct():
    meme = {
        "title": "Titulo",
        "url": "https://cdn.discordapp.com/attachments/1/2/img.jpg",
        "permalink": None,
        "subreddit": "comunidad",
        "upvotes": 3,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert files == []
    assert embeds[0].image.url == "https://cdn.discordapp.com/attachments/1/2/img.jpg"


def test_parse_rss_entries_unescapes_double_encoded_ampersands():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <category label="r/maau" term="maau"/>
    <content type="html">&lt;a href="https://preview.redd.it/abc.jpeg?width=320&amp;amp;crop=smart&amp;amp;auto=webp&amp;amp;s=sig"&gt;[link]&lt;/a&gt;</content>
    <link href="https://www.reddit.com/r/MAAU/comments/x/titulo/"/>
    <title>Meme con query</title>
  </entry>
</feed>"""
    posts = memes._parse_rss_entries(rss)
    assert len(posts) == 1
    url = posts[0]["url"]
    assert "&amp;" not in url
    assert "&" in url
    assert url.startswith("https://preview.redd.it/abc.jpeg?width=320")


@pytest.mark.asyncio
async def test_prepare_memes_unescapes_url_before_download(monkeypatch):
    captured = {}

    async def fake_download(url):
        captured["url"] = url
        return b"fake-image-bytes"

    monkeypatch.setattr(memes, "_download_image", fake_download)

    meme = {
        "title": "Titulo",
        "url": "https://preview.redd.it/abc.jpeg?width=320&amp;crop=smart",
        "permalink": "https://www.reddit.com/r/maau/comments/x/",
        "subreddit": "maau",
        "upvotes": 0,
        "is_video": False,
    }
    embeds, files = await memes.prepare_memes([meme])
    assert len(files) == 1
    assert "&amp;" not in captured["url"]
    assert "&" in captured["url"]


def test_meme_api_url_validation(monkeypatch):

    def run_fetch(payload):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, headers=None):
                return FakeResponse()

        monkeypatch.setattr(memes.httpx, "AsyncClient", FakeClient)
        return asyncio.run(memes._fetch_from_meme_api("maau"))

    video = run_fetch({
        "title": "v", "url": "https://videos.memedroid.com/videos/x.mp4",
        "ups": 1, "postLink": "", "subreddit": "maau", "nsfw": False,
    })
    assert video is not None
    assert video["is_video"] is True

    gallery = run_fetch({
        "title": "g", "url": "https://www.reddit.com/gallery/abc",
        "ups": 1, "postLink": "", "subreddit": "maau", "nsfw": False,
    })
    assert gallery is None

    image = run_fetch({
        "title": "i", "url": "https://i.redd.it/abc.png",
        "ups": 1, "postLink": "", "subreddit": "maau", "nsfw": False,
    })
    assert image is not None
    assert image["is_video"] is False


def test_reroll_rate_limit():
    memes.MemeRerollView._rolls.clear()
    allowed, remaining = memes.MemeRerollView._can_reroll(999)
    assert allowed is True
    allowed, _ = memes.MemeRerollView._can_reroll(999)
    assert allowed is True
    allowed, _ = memes.MemeRerollView._can_reroll(999)
    assert allowed is True
    allowed, _ = memes.MemeRerollView._can_reroll(999)
    assert allowed is False
    memes.MemeRerollView._rolls.clear()


@pytest.mark.asyncio
async def test_get_memes_distinct(db, monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_subreddits", "maau")

    def fake_posts():
        posts = []
        for i in range(5):
            post = make_post(url=f"https://i.redd.it/fake{i}.jpg")
            post["subreddit"] = "maau"
            posts.append(post)
        return posts

    async def fake_rss(sub):
        return fake_posts(), False

    monkeypatch.setattr(memes, "_fetch_reddit_rss", fake_rss)

    async def fake_meme_api(sub):
        return None

    monkeypatch.setattr(memes, "_fetch_from_meme_api", fake_meme_api)

    got = await memes.get_memes(3)
    assert 1 <= len(got) <= 3
    urls = {m["url"] for m in got}
    assert len(urls) == len(got)


def test_fetch_reddit_rss_429_returns_limited(monkeypatch):
    class FakeResponse:
        status_code = 429
        text = ""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(memes.httpx, "AsyncClient", FakeClient)

    posts, limited = asyncio.run(memes._fetch_reddit_rss("maau"))
    assert posts == []
    assert limited is True


def test_get_subreddit_pool_from_config(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_subreddits", "MAAU, memexico, 2latinoforyou")
    pool = memes.get_subreddit_pool()
    assert pool == ["maau", "memexico", "2latinoforyou"]


def test_get_subreddit_pool_default(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "meme_subreddits", "")
    pool = memes.get_subreddit_pool()
    assert "memes" in pool
    assert "dankmemes" in pool
    assert "gaming" in pool


@pytest.mark.asyncio
async def test_meme_history_dedup(db):
    url = "https://i.redd.it/test.jpg"
    assert await db.is_meme_seen(url) is False
    await db.add_meme_history(url, "title")
    assert await db.is_meme_seen(url) is True


@pytest.mark.asyncio
async def test_meme_history_insert_ignore(db):
    url = "https://i.redd.it/dup.jpg"
    await db.add_meme_history(url, "t1")
    await db.add_meme_history(url, "t2")
    conn = None
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM meme_history WHERE url = ?", (url,)
        ).fetchone()[0]
    finally:
        if conn:
            conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_meme_history_prune(db):
    import time
    import sqlite3
    old_url = "https://i.redd.it/old.jpg"
    await db.add_meme_history(old_url, "old")
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute(
            "UPDATE meme_history SET posted_at = ? WHERE url = ?",
            (time.time() - 60 * 86400, old_url)
        )
        conn.commit()
    finally:
        conn.close()
    await db.prune_meme_history(30)
    assert await db.is_meme_seen(old_url) is False
