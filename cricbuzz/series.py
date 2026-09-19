"""Series endpoints: the series lists and archive, and every tab of one
series (matches, squads, points table, stats, venues, news).

`series` takes a bare id or any cricbuzz.com series link (refs.resolve_series).
"""
from urllib.parse import urlencode

from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, gather, get_json, get_page
from .rsc import find_first, page_rows, undefined_to_none


def _sid(series):
    return refs.resolve_series(series)


def _tab(series_id, tab=""):
    return f"/cricket-series/{series_id}/series" + (f"/{tab}" if tab else "")


# ---- lists ----------------------------------------------------------------------------------

def get_list(type=None):
    """Current and upcoming series of one category (the site's schedule
    list; rendered as HTML only, so each entry carries its date range as
    shown, without a year)."""
    category = type or "all"
    html = get_page(f"/cricket-schedule/series/{category}")
    items = P.series_list(html)
    return {"type": category, "series_count": len(items), "series": items}


def get_archive(year=None):
    """Every series of one year (default: the current one), with dates."""
    path = "/cricket-scorecard-archives" + (f"/{year}" if year else "")
    html = get_page(path)
    data = find_first(page_rows(html), "seriesMapProto")
    years = P.archive_years(data)
    return {"year": year, "years": years}


# ---- one series --------------------------------------------------------------------------------

def _page(series_id, tab, key, *, optional=False, where=None):
    html = get_page(_tab(series_id, tab), optional=optional)
    if not html:
        return None
    rows = page_rows(html)
    data = find_first(rows, key, where=where)
    return undefined_to_none(data) if data is not None else None


def get_details(series):
    """The series card (dates, category, match counts), its squads and its
    latest stories."""
    series_id = _sid(series)
    parts = gather({
        "squads": lambda: _page(series_id, "squads", "seriesInfoData"),
        "home": lambda: _page(series_id, "", "storyList", optional=True),
    })
    if parts["squads"] is None and parts["home"] is None:
        raise CricbuzzNotFound(f"series {series_id} not found")
    squads_page = parts["squads"] or {}
    info = P.series_info(squads_page.get("seriesInfoData")) or {"id": series_id, "name": None, "link": P.series_link(series_id)}
    squads_block = (squads_page.get("data") or {})
    info["squads"] = P.series_squads(squads_block)
    stories = (parts["home"] or {}).get("storyList") or []
    info["news"] = [s for s in (P.story(x) for x in stories if isinstance(x, dict)) if s]
    return info


def get_matches(series):
    """All fixtures and results of the series, day by day."""
    series_id = _sid(series)
    data = _page(series_id, "matches", "matchesData")
    if data is None:
        raise CricbuzzNotFound(f"series {series_id} has no matches page")
    block = data.get("matchesData") or {}
    days = P.dated_matches(block.get("matchDetails"))
    return {"series_id": series_id, "day_count": len(days),
            "match_count": sum(d["match_count"] for d in days), "days": days}


def get_squads(series):
    """The squads announced for the series (one per team per format);
    fetch a squad's players with /series/squad-players."""
    series_id = _sid(series)
    data = _page(series_id, "squads", "squads", where=lambda d: isinstance(d.get("squads"), list))
    if data is None:
        raise CricbuzzNotFound(f"series {series_id} has no squads")
    return {"series": P.series_stub(series_id, data.get("seriesName")), "groups": P.series_squads(data)}


def get_squad_players(series, squad):
    series_id = _sid(series)
    data = get_json(f"/api/cricket-series/series-squads/{series_id}/{squad}")
    if data is None:
        raise CricbuzzNotFound(f"squad {squad} of series {series_id} not found")
    groups = P.series_squad_players(data)
    return {"series_id": series_id, "squad_id": squad,
            "player_count": sum(len(g["players"]) for g in groups), "groups": groups}


def get_points_table(series):
    series_id = _sid(series)
    data = _page(series_id, "points-table", "pointsTableData")
    if data is None:
        raise CricbuzzNotFound(f"series {series_id} has no points table")
    return P.points_table(data.get("pointsTableData"))


def get_stats(series, stats_type=None, format=None, team=None):
    """Series leaderboards (most runs, most wickets, …). Without `format`
    the series' default format table is returned; `team` narrows to one
    team id."""
    series_id = _sid(series)
    token = refs.STATS_TYPES.get(stats_type or "most-runs", stats_type)
    if not format:
        data = _page(series_id, "stats", "initialStats")
        if data is None:
            raise CricbuzzNotFound(f"series {series_id} has no stats")
        initial = data.get("initialStats") or {}
        selected = data.get("initialSelectedFilters") or {}
        format = refs.FORMAT_NAMES.get(str(selected.get("matchTypeId")), None)
        if token == "mostRuns" and (team in (None, "all")):
            table = next((v for k, v in initial.items() if k.endswith("StatsList")), None)
            return _stats_response(series_id, token, format, team, table, data.get("statsTypes"))
    query = {"statsType": token, "matchType": refs.FORMAT_IDS.get(format, format) if format else "", "team": team or "all"}
    data = get_json(f"/api/cricket-series/series-stats/{series_id}?{urlencode(query)}")
    if data is None:
        raise CricbuzzNotFound(f"series {series_id} has no {stats_type or 'most-runs'} stats")
    table = next((v for k, v in data.items() if k.endswith("StatsList")), None)
    return _stats_response(series_id, token, format, team, table, None)


def _stats_response(series_id, token, format, team, table, types):
    out = P.stats_table(table or {})
    out.pop("filters", None)
    return {
        "series_id": series_id,
        "stats_type": refs.stats_type_public(token),
        "name": refs.STATS_TYPE_LABELS.get(token),
        "format": format,
        "team": team or "all",
        "row_count": len(out["rows"]),
        "headers": out["headers"],
        "rows": out["rows"],
        "stats_types_available": P.stats_types((types or {}).get("types")) if types else None,
    }


def get_venues(series):
    series_id = _sid(series)
    data = _page(series_id, "venues", "venueData")
    if data is None:
        raise CricbuzzNotFound(f"series {series_id} has no venues")
    block = data.get("venueData") or {}
    venues = [v for v in (P.series_venue(x) for x in block.get("seriesVenue") or []) if v]
    return {"series": P.series_stub(series_id, block.get("seriesName")), "venue_count": len(venues), "venues": venues}


def get_news(series, before=None):
    """Stories tagged with the series; `before` (a story id from the
    previous page) pages backwards."""
    series_id = _sid(series)
    if before:
        data = get_json(f"/api/cricket-series/paginate/news/{series_id}/{before}") or {}
    else:
        data = _page(series_id, "news", "storyList") or {}
    stories = [s for s in (P.story(x) for x in data.get("storyList") or [] if isinstance(x, dict)) if s]
    return {"series_id": series_id, "story_count": len(stories), "stories": stories,
            "next_before": stories[-1]["id"] if stories else None}
