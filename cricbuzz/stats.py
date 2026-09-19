"""Stats endpoints: ICC rankings, ICC standings (WTC / CWC Super League),
all-time records with filters, and venues.
"""
from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, get_json, get_page
from .rsc import find_first, page_rows, undefined_to_none


def get_rankings(category=None, gender=None, format=None):
    """ICC player or team rankings. All three formats come back unless
    `format` picks one."""
    category = category or "batting"
    gender = gender or "men"
    html = get_page(f"/cricket-stats/icc-rankings/{gender}/{category}")
    data = find_first(page_rows(html), "formatTypesData")
    if data is None:
        raise CricbuzzNotFound(f"no {gender} {category} rankings")
    is_teams = category == "teams"
    formats = {}
    for name, block in (data.get("formatTypesData") or {}).items():
        if format and name != format:
            continue
        rows = [P.ranking_row(undefined_to_none(r), teams=is_teams) for r in (block or {}).get("rank") or [] if isinstance(r, dict)]
        formats[name] = rows
    return {
        "category": category,
        "gender": gender,
        "format": format,
        "default_format": P.clean(data.get("initialFormatType")),
        "rankings": formats,
    }


def get_standings(format=None, season=None):
    """ICC championship standings: the World Test Championship (test) or the
    CWC Super League (odi). Without `season` the active season is used."""
    format = format or "test"
    format_id = refs.FORMAT_IDS.get(format, format)
    if not season:
        catalogue = get_json(f"/api/points-table/{format_id}/0") or {}
        seasons = catalogue.get("seasonStandings") or []
        active = next((s for s in seasons if s.get("isActive")), seasons[0] if seasons else None)
        if not active:
            raise CricbuzzNotFound(f"no {format} standings")
        season = active.get("id")
    data = get_json(f"/api/points-table/{format_id}/{season}")
    if data is None:
        raise CricbuzzNotFound(f"no {format} standings for season {season}")
    out = P.icc_standings(data, format)
    out["season_id"] = P.to_int(season)
    return out


def get_records(stats_type=None, format=None, year=None, team=None, opponent=None):
    """All-time records tables (most runs, most wickets, best bowling, …)
    filtered by format, year, team and opponent."""
    token = refs.STATS_TYPES.get(stats_type or "most-runs", stats_type)
    fmt = refs.FORMAT_IDS.get(format or "test", format)
    path = f"/api/cricket-stats/stats-table/{token}/{fmt}/{year or 'all'}/{team or 'all'}/{opponent or 'all'}"
    data = get_json(path)
    if data is None:
        raise CricbuzzNotFound(f"no records for {stats_type or 'most-runs'}")
    out = P.stats_table(data)
    return {
        "stats_type": refs.stats_type_public(token),
        "name": refs.STATS_TYPE_LABELS.get(token),
        "format": format or "test",
        "year": year or "all",
        "team": team or "all",
        "opponent": opponent or "all",
        "row_count": len(out["rows"]),
        "headers": out["headers"],
        "rows": out["rows"],
        "filters": out["filters"],
    }


def get_record_types():
    """The records catalogue (what `stats_type` accepts)."""
    types = [{"stats_type": public, "name": refs.STATS_TYPE_LABELS.get(token),
              "category": "Batting" if token in refs.BATTING_STATS else "Bowling"}
             for public, token in refs.STATS_TYPES.items()]
    return {"type_count": len(types), "types": types, "formats": list(refs.FORMAT_IDS)}


def get_venue(venue):
    """A ground's profile and its Test/ODI/T20 records."""
    venue_id = refs.resolve_venue(venue)
    html = get_page(f"/cricket-venues/{venue_id}/venue")
    data = find_first(page_rows(html), "venueDetails")
    if data is None:
        raise CricbuzzNotFound(f"venue {venue_id} not found")
    return P.venue_details(undefined_to_none(data), venue_id)
