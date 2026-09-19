"""Team endpoints: the team lists and every tab of one team (players,
schedule, results, stats, news, photos).

`team` takes a bare id or any cricbuzz.com team link (refs.resolve_team).
The roster and the team index are HTML-only pages (parsers.grouped_links).
"""
from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, gather, get_json, get_page
from .rsc import find_first, page_rows, undefined_to_none


def _tid(team):
    return refs.resolve_team(team)


def _tab(team_id, tab=""):
    return f"/cricket-team/team/{team_id}" + (f"/{tab}" if tab else "")


def get_list(type=None):
    """Teams of one category (international, domestic, league, women),
    grouped the way the site groups them (Test teams, Associate teams, …)."""
    category = type or "international"
    path = "/cricket-team" if category == "international" else f"/cricket-team/{category}"
    html = get_page(path)
    groups = [{"group": g["group"], "team_count": len(g["items"]),
               "teams": [{"id": i["id"], "name": i["name"], "link": i["link"], "flag": i["image"]} for i in g["items"]]}
              for g in P.grouped_links(html, "/cricket-team/")]
    groups = [g for g in groups if g["teams"]]
    return {"type": category, "team_count": sum(g["team_count"] for g in groups), "groups": groups}


def _page(team_id, tab, key, *, optional=False, where=None):
    html = get_page(_tab(team_id, tab), optional=optional)
    if not html:
        return None
    data = find_first(page_rows(html), key, where=where)
    return undefined_to_none(data) if data is not None else None


def get_details(team):
    """The team card plus its latest stories."""
    team_id = _tid(team)
    parts = gather({
        "home": lambda: _page(team_id, "", "teamInfo"),
        "news": lambda: _page(team_id, "news", "storyList", optional=True),
    })
    if parts["home"] is None:
        raise CricbuzzNotFound(f"team {team_id} not found")
    info = P.team_info(parts["home"].get("teamInfo")) or {"id": team_id, "name": P.clean(parts["home"].get("heading")),
                                                          "link": P.team_link(team_id)}
    stories = (parts["news"] or {}).get("storyList") or []
    info["news"] = [s for s in (P.story(x) for x in stories if isinstance(x, dict)) if s]
    return info


def get_players(team):
    """The current roster grouped by role (HTML-only upstream page)."""
    team_id = _tid(team)
    html = get_page(_tab(team_id, "players"))
    groups = [{"role": g["group"], "player_count": len(g["items"]), "players": g["items"]}
              for g in P.grouped_links(html, "/profiles/")]
    groups = [g for g in groups if g["players"]]
    return {"team_id": team_id, "player_count": sum(g["player_count"] for g in groups), "groups": groups}


def _matches(team_id, tab):
    data = _page(team_id, tab, "teamMatchesData")
    if data is None:
        raise CricbuzzNotFound(f"team {team_id} has no {tab}")
    days = P.dated_matches(data.get("teamMatchesData"))
    return {"team_id": team_id, "day_count": len(days), "match_count": sum(d["match_count"] for d in days), "days": days}


def get_schedule(team):
    return _matches(_tid(team), "schedule")


def get_results(team):
    return _matches(_tid(team), "results")


def get_stats(team, stats_type=None, format=None, year=None, opponent=None):
    """Team leaderboards (most runs, best bowling, …) with the format, year
    and opponent filters the site offers."""
    team_id = _tid(team)
    token = refs.STATS_TYPES.get(stats_type or "most-runs", stats_type)
    fmt = refs.FORMAT_IDS.get(format or "test", format)
    path = f"/api/cricket-team/stats-table/{team_id}/{token}/{fmt}/{year or 'all'}/{opponent or 'all'}"
    data = get_json(path)
    if data is None:
        raise CricbuzzNotFound(f"team {team_id} has no {stats_type or 'most-runs'} stats")
    out = P.stats_table(data)
    return {
        "team_id": team_id,
        "stats_type": refs.stats_type_public(token),
        "name": refs.STATS_TYPE_LABELS.get(token),
        "format": format or "test",
        "year": year or "all",
        "opponent": opponent or "all",
        "row_count": len(out["rows"]),
        "headers": out["headers"],
        "rows": out["rows"],
        "filters": out["filters"],
    }


def get_news(team, before=None):
    team_id = _tid(team)
    if before:
        data = get_json(f"/api/cricket-team/paginate/news/{team_id}/{before}") or {}
    else:
        data = _page(team_id, "news", "storyList") or {}
    stories = [s for s in (P.story(x) for x in data.get("storyList") or [] if isinstance(x, dict)) if s]
    return {"team_id": team_id, "story_count": len(stories), "stories": stories,
            "next_before": stories[-1]["id"] if stories else None}


def get_photos(team, before=None):
    """Photo galleries tagged with the team; `before` is the `published_at`
    epoch of the last gallery on the previous page."""
    team_id = _tid(team)
    stamp = before or 0
    data = get_json(f"/api/cricket-team/paginate/photos/{team_id}/{stamp}") or {}
    galleries = [g for g in (P.gallery_summary(x) for x in data.get("photoGalleryInfoList") or []) if g]
    raw_last = (data.get("photoGalleryInfoList") or [{}])[-1] if data.get("photoGalleryInfoList") else {}
    return {"team_id": team_id, "gallery_count": len(galleries), "galleries": galleries,
            "next_before": P.to_int((raw_last.get("photoGalleryInfo") or {}).get("publishedTime")) if raw_last else None}
