"""Match endpoints: the live/recent/upcoming lists, the schedule, and every
tab of one match.

`match` is one param that takes a bare Cricbuzz match id or any cricbuzz.com
match link (refs.resolve_match). Detail tabs mix two surfaces: the /api
route handlers (miniscore, live score, commentary, scorecard, highlights,
overs, ball map, partnerships) and the server-rendered pages whose RSC
payload carries what no handler exposes (officials and series results on
the commentary page, squads, graphs, player performance).

The Hundred is served by a parallel set of `h`-prefixed handlers upstream
(`/hminiscore`, `/hscorecard`, `/hcomm`, …); every handler call here falls
back to that variant when the plain one answers empty, so a caller never
has to know the competition.
"""
from datetime import datetime, timezone

from . import parsers as P
from . import refs
from .fetch import CricbuzzNotFound, gather, get_json, get_page, run_parallel
from .rsc import deref, find_first, page_rows, undefined_to_none

_LIST_PATHS = {
    "live": "/cricket-match/live-scores",
    "recent": "/cricket-match/live-scores/recent-matches",
    "upcoming": "/cricket-match/live-scores/upcoming-matches",
}


def _mid(match):
    return refs.resolve_match(match)


def _handler(plain, hundred, *, optional=True):
    """A handler, then its Hundred twin when the plain one has no body."""
    data = get_json(plain, optional=True)
    if data is None and hundred:
        data = get_json(hundred, optional=True)
    if data is None and not optional:
        raise CricbuzzNotFound(f"{plain} has no data")
    return data


def _epoch_ms(value):
    """`before`: epoch milliseconds, epoch seconds or an ISO-8601 time -> ms."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        return number if number > 10**11 else number * 1000
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("before must be an epoch timestamp or an ISO-8601 time")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp() * 1000)


# ---- lists ---------------------------------------------------------------------------------

def _filter_groups(groups, type_name):
    if not type_name or type_name == "all":
        return groups
    return [g for g in groups if (g.get("type") or "").lower() == type_name.lower()]


def _match_list(kind, type_name):
    html = get_page(_LIST_PATHS[kind])
    rows = page_rows(html)
    # The layout rows carry the sidebar's `typeMatches` copy of the LIVE
    # list on every page; the page's own list (recent / upcoming) is the
    # `matches` prop of its list component — the same group shape.
    own = find_first(rows, "matches", where=lambda d: isinstance(d.get("matches"), list) and d["matches"]
                     and isinstance(d["matches"][0], dict) and "matchType" in d["matches"][0])
    sidebar = find_first(rows, "typeMatches")
    data = {"typeMatches": own["matches"]} if own else (sidebar or {})
    groups = _filter_groups(P.type_matches(data), type_name)
    return {
        "kind": kind,
        "type": type_name or "all",
        "types_available": [P.clean(t) for t in ((sidebar or {}).get("filters") or {}).get("matchType") or []],
        "match_count": sum(s["match_count"] for g in groups for s in g["series"]),
        "groups": groups,
        "updated_at": P.iso_time((sidebar or {}).get("responseLastUpdated")),
    }


def get_live(type=None):
    """Matches in progress (and the day's just-finished ones), grouped by
    International / League / Domestic / Women and then by series."""
    return _match_list("live", type)


def get_recent(type=None):
    """Recently completed matches, grouped like the live list."""
    return _match_list("recent", type)


def get_upcoming(type=None):
    """Upcoming matches, grouped like the live list."""
    return _match_list("upcoming", type)


def get_schedule(type=None, date=None):
    """The fixture calendar (day by day) for one category."""
    category = type or "international"
    html = get_page(f"/cricket-schedule/upcoming-series/{category}")
    data = find_first(page_rows(html), "matchScheduleMap")
    days = P.schedule_days(data)
    if date:
        days = [d for d in days if d.get("date") == date]
    return {
        "type": category,
        "day_count": len(days),
        "match_count": sum(d["match_count"] for d in days),
        "days": days,
    }


# ---- one match ---------------------------------------------------------------------------------

def _page_data(match_id, page, key, *, where=None, label=None):
    html = get_page(f"/{page}/{match_id}/{label or 'match'}")
    rows = page_rows(html)
    data = find_first(rows, key, where=where)
    if data is None:
        raise CricbuzzNotFound(f"match {match_id} has no {key.replace('Data', '').lower()} data")
    return rows, undefined_to_none(data)


def get_details(match):
    """Everything about one match in one call: the header with officials,
    toss, result and awards, the series scoreline, the venue, the live
    state of the current innings and the viewer counter."""
    match_id = _mid(match)

    def page():
        rows, data = _page_data(match_id, "live-cricket-scores", "commentaryPageData")
        return data

    parts = gather({
        "page": page,
        "mini": lambda: _handler(f"/api/mcenter/{match_id}/miniscore", f"/api/mcenter/{match_id}/hminiscore"),
        "views": lambda: get_json(f"/api/mcenter/views-counter/{match_id}"),
    })
    if parts["page"] is None:
        raise CricbuzzNotFound(f"match {match_id} not found")
    info = P.match_info(parts["page"].get("matchInfo")) or {"id": match_id, "link": P.match_link(match_id)}
    mini = parts["mini"] or {}
    header = P.match_header(mini.get("matchHeader"))
    if header:
        # the handler's header carries the freshest status/result
        for key in ("state", "status", "status_category", "is_complete", "result", "players_of_the_match",
                    "players_of_the_series", "innings_order", "revised_target"):
            if header.get(key) not in (None, [], {}):
                info[key] = header[key]
    views = parts["views"] or {}
    info["live"] = P.miniscore(mini.get("miniscore"))
    info["viewers"] = [{"type": P.clean(v.get("type")), "label": P.clean(v.get("title")), "count": P.clean(v.get("count"))}
                       for v in views.get("viewersCount") or [] if isinstance(v, dict)] or None
    info["updated_at"] = P.iso_time(mini.get("miniscore", {}).get("responseLastUpdated") if isinstance(mini.get("miniscore"), dict) else None)
    return info


def get_live_score(match):
    """The polling surface: current innings state plus the last few balls
    (the site itself refreshes this every 3 seconds during play)."""
    match_id = _mid(match)
    data = _handler(f"/api/mcenter/livescore/{match_id}", None, optional=False)
    mini = _handler(f"/api/mcenter/{match_id}/miniscore", f"/api/mcenter/{match_id}/hminiscore")
    return {
        "match": P.match_header((mini or {}).get("matchHeader")),
        "live": P.miniscore(data.get("miniscore")),
        "recent_balls": P.commentary_list(data.get("commentaryList")),
    }


def get_scorecard(match):
    """Full scorecard: every innings with batting, bowling, extras, fall of
    wickets, partnerships and powerplays."""
    match_id = _mid(match)
    data = _handler(f"/api/mcenter/scorecard/{match_id}", f"/api/mcenter/hscorecard/{match_id}", optional=False)
    return P.scorecard(data)


def get_commentary(match, innings=None, before=None):
    """Ball-by-ball commentary, newest first. Without `before` the latest
    page (with the live state); with `before` (a timestamp from an earlier
    page's `next_before`) the entries older than it — `innings` is then
    required by the upstream."""
    match_id = _mid(match)
    stamp = _epoch_ms(before)
    if stamp:
        if not innings:
            raise ValueError("innings is required together with before")
        data = _handler(f"/api/mcenter/commentary-pagination/{match_id}/{innings}/{stamp}",
                        f"/api/mcenter/hcommentary-pagination/{match_id}/{innings}/{stamp}") or []
        entries = P.commentary_feed(data)
        return {
            "innings_id": innings,
            "entry_count": len(entries),
            "commentary": entries,
            "next_before": P.to_int((data[-1] or {}).get("timestamp")) if data else None,
        }
    data = _handler(f"/api/mcenter/comm/{match_id}", f"/api/mcenter/hcomm/{match_id}", optional=False)
    entries = P.commentary_feed(data.get("matchCommentary"))
    if innings:
        entries = [e for e in entries if e.get("innings_id") == innings]
    raw_feed = data.get("matchCommentary") or {}
    oldest = min((P.to_int(k) or 0 for k in raw_feed), default=None) if isinstance(raw_feed, dict) else None
    return {
        "match": P.match_header(data.get("matchHeader")),
        "live": P.miniscore(data.get("miniscore")),
        "entry_count": len(entries),
        "commentary": entries,
        "next_before": oldest or None,
        "updated_at": P.iso_time(data.get("responseLastUpdated")),
    }


def get_full_commentary(match, innings=None):
    """Every ball of one innings (default: the first) with the batter and
    bowler figures at that moment."""
    match_id = _mid(match)
    innings = innings or 1
    data = _handler(f"/api/mcenter/{match_id}/full-commentary/{innings}",
                    f"/api/mcenter/{match_id}/hfull-commentary/{innings}", optional=False)
    details = data.get("matchDetails") or {}
    blocks = []
    for block in data.get("commentary") or []:
        entries = P.commentary_list(block.get("commentaryList"))
        blocks.append({"innings_id": P.to_int(block.get("inningsId")), "entry_count": len(entries), "commentary": entries})
    return {
        "match": P.match_header(details.get("matchHeader")),
        "live": P.miniscore(details.get("miniscore")),
        "innings": blocks,
    }


def get_highlights(match, innings=None):
    """Only the key balls of one innings (wickets, fours, sixes, milestones)."""
    match_id = _mid(match)
    innings = innings or 1
    data = _handler(f"/api/mcenter/highlights/{match_id}/{innings}",
                    f"/api/mcenter/hhighlights/{match_id}/{innings}", optional=False)
    entries = P.commentary_list(data.get("commentaryList"))
    return {
        "match": P.match_header(data.get("matchHeader")),
        "innings_id": innings,
        "has_content": not P.to_bool(data.get("enableNoContent")),
        "entry_count": len(entries),
        "highlights": entries,
        "updated_at": P.iso_time(data.get("responseLastUpdated")),
    }


def get_overs(match, innings=None, before=None):
    """Over-by-over summary of one innings, newest first, with `next_before`
    for the older page."""
    match_id = _mid(match)
    innings = innings or 1
    stamp = _epoch_ms(before)
    path = f"/api/mcenter/over-by-over/{match_id}/{innings}" + (f"/{stamp}" if stamp else "")
    data = get_json(path) or {}
    overs = [P.over_summary(o) for o in data.get("paginatedData") or [] if isinstance(o, dict)]
    next_url = data.get("nextPaginationURL") or ""
    next_before = P.to_int(next_url.rstrip("/").rsplit("/", 1)[-1]) if next_url else None
    return {"innings_id": innings, "over_count": len(overs), "overs": overs, "next_before": next_before}


def get_ball_by_ball(match, innings=None):
    """Every delivery of one innings with runs, events and who faced/bowled it."""
    match_id = _mid(match)
    innings = innings or 1
    data = get_json(f"/api/mcenter/balls-map/{match_id}/{innings}")
    if data is None:
        raise CricbuzzNotFound(f"match {match_id} has no ball data for innings {innings}")
    return {"innings_id": innings, **P.balls_map(data)}


def get_partnerships(match):
    match_id = _mid(match)
    data = get_json(f"/api/mcenter/partnership-graph/{match_id}")
    if data is None:
        raise CricbuzzNotFound(f"match {match_id} has no partnership data")
    innings = P.partnership_graph(data)
    return {"innings_count": len(innings), "innings": innings}


def get_squads(match):
    """Playing XI, bench and support staff of both sides."""
    match_id = _mid(match)
    rows, data = _page_data(match_id, "cricket-match-squads", "team1",
                            where=lambda d: isinstance(d.get("team1"), dict) and "players" in d["team1"])
    return P.match_squads(data)


def get_graphs(match):
    """Runs, run rate, runs per over and win probability per over, plus the
    partnerships of every innings."""
    match_id = _mid(match)

    def page():
        rows, data = _page_data(match_id, "live-cricket-graphs", "graphsData")
        return data["graphsData"]

    parts = gather({"graphs": page, "partnerships": lambda: get_json(f"/api/mcenter/partnership-graph/{match_id}")})
    if parts["graphs"] is None:
        raise CricbuzzNotFound(f"match {match_id} has no graphs")
    out = P.match_graphs(parts["graphs"])
    out["partnerships"] = P.partnership_graph(parts["partnerships"]) if parts["partnerships"] else []
    return out


def get_player_performance(match, player, type=None):
    """One player's batting or bowling in one match: the summary card, the
    bowler/batter match-ups and the balls they faced or bowled."""
    match_id = _mid(match)
    player_id = refs.resolve_player(player)
    category = type or "batting"
    html = get_page(f"/player-match-performance/match/{match_id}/player/{player_id}/{category}")
    data = find_first(page_rows(html), "initialData")
    if data is None:
        raise CricbuzzNotFound(f"no {category} performance for player {player_id} in match {match_id}")
    data = undefined_to_none(data)
    out = P.player_performance(data.get("initialData"))
    out["match_id"] = match_id
    out["format"] = P.clean(data.get("matchFormat"))
    return out


def get_news(match):
    """Stories filed on the match page."""
    match_id = _mid(match)
    html = get_page(f"/cricket-match-news/{match_id}/match")
    rows = page_rows(html)
    block = find_first(rows, "storyList")
    if block is not None:
        stories = [P.story(s) for s in block.get("storyList") or [] if isinstance(s, dict)]
    else:
        stories = P.news_cards(html)
    return {"match_id": match_id, "story_count": len(stories), "stories": stories}
