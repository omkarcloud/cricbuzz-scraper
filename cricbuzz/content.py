"""Content endpoints: news (lists, stories, topics, authors), photo
galleries, videos and the IPL/WPL auction tracker.

News categories are HTML pages (the /api/cricket-news pagination handler
ignores its category segment, so only the latest feed pages via the API);
a story page is parsed with its JSON-LD for the dates.
"""
from urllib.parse import quote

from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, get_json, get_page
from .rsc import find_first, page_rows, undefined_to_none

# The pagination handler wants "the id to page back from"; this stands in
# for "the newest" when a caller has none.
_LATEST_ID = 999999999


# ---- news ------------------------------------------------------------------------------------

def _stories_from(block):
    return [s for s in (P.story(x) for x in (block or {}).get("storyList") or [] if isinstance(x, dict)) if s]


def get_news(category=None, before=None):
    """Stories of one category, newest first. `before` (a story id from the
    previous page) pages backwards — supported for `latest` only, the
    upstream has no pagination for the editorial categories."""
    category = category or "latest"
    if before:
        if category != "latest":
            raise ValueError("before is only supported for category=latest")
        data = get_json(f"/api/cricket-news/{before}/1") or {}
        stories = [s for s in (P.story(x) for x in data.get("paginatedData") or [] if isinstance(x, dict)) if s]
        next_url = data.get("nextPaginationURL") or ""
        next_before = P.to_int(next_url.strip("/").split("/")[-2]) if next_url.count("/") >= 3 else None
        return {"category": category, "story_count": len(stories), "stories": stories, "next_before": next_before}
    html = get_page(refs.NEWS_CATEGORIES[category])
    stories = P.news_cards(html)
    return {"category": category, "story_count": len(stories), "stories": stories,
            "next_before": stories[-1]["id"] if stories and category == "latest" else None}


def get_article(news):
    """One story: headline, author, dates, cover image, body and tags."""
    news_id = refs.resolve_news(news)
    html = get_page(f"/cricket-news/{news_id}/story")
    return P.news_article(html, news_id)


def get_topics():
    """The editorial topics (story collections) the site maintains."""
    html = get_page("/cricket-news/info")
    topics = P.news_topics(html)
    return {"topic_count": len(topics), "topics": topics}


def get_topic_news(topic, before=None):
    """Stories filed under one topic; `before` pages backwards."""
    topic_id = refs.resolve_topic(topic)
    data = get_json(f"/api/cricket-news/topics/{before or _LATEST_ID}/{topic_id}")
    if data is None:
        raise CricbuzzNotFound(f"topic {topic_id} has no stories")
    stories = [s for s in (P.story(x) for x in data.get("paginatedData") or [] if isinstance(x, dict)) if s]
    return {"topic_id": topic_id, "story_count": len(stories), "stories": stories,
            "next_before": stories[-1]["id"] if stories else None}


def get_author(author):
    """A staff writer's card and latest stories."""
    author_id = refs.resolve_author(author)
    html = get_page(f"/cricket-news/author/writer/{author_id}")
    rows = page_rows(html)
    info = find_first(rows, "authorInfo")
    if info is None:
        raise CricbuzzNotFound(f"author {author_id} not found")
    raw = undefined_to_none(info.get("authorInfo") or {})
    stories = _stories_from(find_first(rows, "storyList"))
    return {
        "id": P.to_int(raw.get("id")) or author_id,
        "name": P.clean(raw.get("name")),
        "designation": P.clean(raw.get("designation")),
        "image": P.image(raw.get("imageId")),
        "link": f"{P.SITE}/cricket-news/author/{P.slugify(raw.get('name'))}/{author_id}",
        "story_count": len(stories),
        "stories": stories,
    }


# ---- photos ------------------------------------------------------------------------------------

def get_photos(before=None):
    """Photo galleries, newest first; `before` is the `published_at` epoch
    (milliseconds) of the last gallery on the previous page."""
    data = get_json(f"/api/cricket-gallery/paginate/gallery-list/{before or 0}") or []
    galleries = [g for g in (P.gallery_summary(x) for x in data if isinstance(x, dict)) if g]
    last = data[-1] if data else {}
    return {"gallery_count": len(galleries), "galleries": galleries,
            "next_before": P.to_int((last.get("photoGalleryInfo") or {}).get("publishedTime")) if last else None}


def get_gallery(gallery):
    gallery_id = refs.resolve_gallery(gallery)
    html = get_page(f"/cricket-gallery/{gallery_id}/gallery")
    return P.gallery_photos(html, gallery_id)


# ---- videos -------------------------------------------------------------------------------------

def get_videos(collection=None, before=None):
    """The video home (every collection with its latest videos), or one
    collection's videos when `collection` is given (`before` = the
    previous page's `next_before`)."""
    if collection:
        data = get_json(f"/api/cricket-videos/collection-pagination/{collection}/{before or 0}")
        if data is None:
            raise CricbuzzNotFound(f"video collection {collection} not found")
        videos = [v for v in (P.video_card(x) for x in data.get("data") or []) if v]
        return {"collection_id": P.to_int(collection), "video_count": len(videos), "videos": videos,
                "next_before": P.to_int(data.get("lastPt"))}
    data = get_json("/api/cricket-videos/0") or {}
    collections = P.video_collections(data)
    return {"collection_count": len(collections), "collections": collections}


def get_video(video):
    """One video: metadata, tags and the HLS stream link."""
    video_id = refs.resolve_video(video)
    html = get_page(f"/cricket-videos/{video_id}/video")
    data = find_first(page_rows(html), "videoUrl")
    if data is None:
        raise CricbuzzNotFound(f"video {video_id} not found")
    return P.video_details(undefined_to_none(data))


# ---- auction ---------------------------------------------------------------------------------------

def get_auction_seasons():
    data = get_json("/api/ipl-auction/seasons") or {}
    seasons = data.get("seasons") or {}
    tournaments = ((seasons.get("tournament") or {}).get("tournaments")) or []
    defaults = data.get("defaults") or {}
    return {
        "tournaments": [{"id": P.clean(t.get("identifier")), "name": P.clean(t.get("title"))} for t in tournaments if isinstance(t, dict)],
        "years": [P.to_int(y) for y in seasons.get("year") or []],
        "default": {"tournament": P.clean((defaults.get("tournament") or {}).get("identifier")),
                    "year": P.to_int(defaults.get("year"))},
    }


def get_auction_players(tournament=None, year=None, status=None, page=None, currency=None, sort=None,
                        country=None, role=None, capped=None, team=None):
    """The auction tracker: sold/unsold/retained players of one season."""
    tournament = tournament or "ipl"
    if not year:
        year = get_auction_seasons()["default"]["year"]
    status = status or "completed"
    field, direction = refs.AUCTION_SORTS.get(sort or "recent", refs.AUCTION_SORTS["recent"])
    page_index = max((page or 1) - 1, 0)
    currency = currency or "inr"
    cap = {True: "capped", False: "uncapped"}.get(capped, "0") if capped is not None else "0"
    role = quote(role, safe="") if role else 0   # a path segment: "/" or " " would break the route
    if status == "completed":
        path = (f"/api/ipl-auction/completed/{page_index}/{currency}/{country or 0}/{cap}/{role}/0/"
                f"{team or 0}/{field}/{direction}/{tournament}/{year}")
    else:
        path = f"/api/ipl-auction/upcoming/{page_index}/{currency}/{country or 0}/{cap}/{role}/default/{tournament}/{year}"
    data = get_json(path)
    if data is None:
        raise CricbuzzNotFound(f"no {status} auction players for {tournament} {year}")
    players = [p for p in (P.auction_player(x) for x in data.get("auctionPlayersList") or []) if p]
    filters = []
    for f in data.get("filters") or []:
        if isinstance(f, dict):
            filters.append({"key": P.clean(f.get("key")), "label": P.clean(f.get("label")),
                            "options": [{"value": P.clean(o.get("value")), "label": P.clean(o.get("label"))}
                                        for o in f.get("options") or [] if isinstance(o, dict)]})
    return {
        "tournament": tournament,
        "year": year,
        "status": status,
        "title": P.clean(data.get("auctionTitle")),
        "current_status": P.clean(data.get("currentStatus")),
        "page": page or 1,
        "player_count": len(players),
        "players": players,
        "filters": filters or None,
    }


def search_auction(query, tournament=None, year=None):
    tournament = tournament or "ipl"
    if not year:
        year = get_auction_seasons()["default"]["year"]
    data = get_json(f"/api/ipl-auction/search/{quote(query.strip(), safe='')}/{tournament}/{year}") or {}
    players = [p for p in (P.auction_player(x) for x in data.get("auctionPlayersList") or []) if p]
    return {"query": query, "tournament": tournament, "year": year, "title": P.clean(data.get("auctionTitle")),
            "player_count": len(players), "players": players}
