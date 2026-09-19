"""Player endpoints: search, trending, the profile, the all-matches log,
the filterable form table and news.

`player` takes a bare id or any cricbuzz.com profile link
(refs.resolve_player). Search is the site's own autocomplete handler
(`/api/player-search/<text>`, two characters minimum upstream).
"""
from urllib.parse import quote

from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, get_json, get_page
from .rsc import deref, find_first, page_rows, undefined_to_none


def _pid(player):
    return refs.resolve_player(player)


def search(query):
    """Players whose name contains the text."""
    data = get_json(f"/api/player-search/{quote(query.strip(), safe='')}") or {}
    players = [p for p in (P.search_player(x) for x in data.get("player") or [] if isinstance(x, dict)) if p]
    return {"query": query, "player_count": len(players), "players": players}


def get_trending():
    """The players people are searching for right now."""
    html = get_page("/profiles")
    groups = P.grouped_links(html, "/profiles/", name_selector="span.text-base",
                             extra=lambda a: {"country": P.clean(a.select_one("span.text-gray-500").get_text()) if a.select_one("span.text-gray-500") else None})
    players = [i for g in groups for i in g["items"]]
    return {"player_count": len(players), "players": players}


def get_details(player):
    """The full profile: bio, personal details, ICC rankings, career
    batting/bowling tables per format, debuts, recent form and news."""
    player_id = _pid(player)
    html = get_page(f"/profiles/{player_id}/player")
    rows = page_rows(html)
    data = find_first(rows, "playerData")
    if data is None:
        raise CricbuzzNotFound(f"player {player_id} not found")
    bio = deref(rows, (data.get("playerData") or {}).get("bio"))
    return P.player_profile(undefined_to_none(data), bio)


def get_matches(player, type=None):
    """Every innings the player has batted (or bowled) in, newest first,
    grouped by series."""
    player_id = _pid(player)
    category = type or "batting"
    html = get_page(f"/profiles/{player_id}/player/all-matches/{category}")
    innings = P.html_table(html)
    return {"player_id": player_id, "type": category, "innings_count": len(innings), "innings": innings}


def get_form(player, type=None):
    """The form table with its filter catalogue (formats, tournaments,
    teams, opponents, venues, years) as the site exposes it."""
    player_id = _pid(player)
    category = type or "batting"
    data = get_json(f"/api/player-profile/player-form/{player_id}?playerFormType={category}")
    if data is None:
        raise CricbuzzNotFound(f"player {player_id} has no {category} form data")
    out = P.player_form(data)
    out["type"] = category
    return out


def get_news(player, before=None):
    player_id = _pid(player)
    if before:
        data = get_json(f"/api/player-profile/paginate/news/{player_id}/{before}") or {}
        stories = [s for s in (P.story(x) for x in data.get("storyList") or [] if isinstance(x, dict)) if s]
    else:
        html = get_page(f"/profiles/{player_id}/player")
        data = find_first(page_rows(html), "playerNews") or {}
        stories = [s for s in (P.story(x) for x in (data.get("playerNews") or {}).get("storyList") or [] if isinstance(x, dict)) if s]
    return {"player_id": player_id, "story_count": len(stories), "stories": stories,
            "next_before": stories[-1]["id"] if stories else None}
