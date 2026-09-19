"""Cricbuzz normalizers: the internal API's camelCase JSON (as relayed by the
site's /api route handlers and embedded in its RSC payload) and the few
HTML-only pages -> one clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical page URLs (always absolute), `image`/`flag` for pictures
(static.cricbuzz.com is a public CDN — `i.jpg?p=det&d=high` serves every
image id at full size, no headers needed), `*_count` for counters,
`is_*`/`has_*` for booleans, ISO-8601 UTC for timestamps (the upstream's
epoch milliseconds), numbers as numbers, null for missing. Entity refs
share one vocabulary: a team is {id, name, short_name, link, flag}, a
player is {id, name, link, image}, a series is {id, name, link}, a venue is
{id, name, city, country, link}.

Deliberately dropped as noise: `appIndex` (SEO title/URL of the page the
data was rendered on), `seriesAdWrapper`/`scheduleAdWrapper`/`adsType`/
`adTag` (ad-slot wrappers, unwrapped in place), `entitlements` (Cricbuzz+
paywall flags, folded into `is_premium`), `imageDetails.src/w/h/aspect/
imageType/priority` (the site's <img> sizing hints; only the image id is
kept), `alertType`, `livestreamEnabledGeo`, `isPollEnabled`/`isFantasyEnabled`/
`isForecastEnabled` (site feature toggles), `matchTeamInfo` duplicates on
miniscore.matchScoreDetails (kept once on the header), `mobileHeaders`/
`mobileValues` (a narrower copy of the web table), `responseLastUpdated`
on sub-objects (kept once as `updated_at`), `commentaryFormats` (rendered
into the text), the `B0$` bold placeholders (substituted), `hideScoreStatus`
(presentation copy of `status`), `playerTeamIds` (a comma string of
`teamNameIds`), `imageHash`, `mappingId` (Kaltura entry id — the
`stream_link` already embeds it).
"""
import html as html_lib
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import refs

SITE = "https://www.cricbuzz.com"
IMG = "https://static.cricbuzz.com/a/img/v1/i1/c{id}/i.jpg?p=det&d=high"

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_PLACEHOLDER_RE = re.compile(r"B(\d+)\$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---- scalars ---------------------------------------------------------------------------

def clean(value):
    """Whitespace-collapsed string, or None for empty / placeholder values."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = _WS_RE.sub(" ", str(value)).strip()
    if text in ("", "-", "--", "$undefined", "null", "None"):
        return None
    return text


def to_int(value):
    if value is None or value == "" or value == "$undefined":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip().replace(",", "")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.0+", text):
        return int(float(text))
    return None


def to_float(value):
    if value is None or value == "" or value == "$undefined":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_number(value):
    """int when the value is integral, else float, else None."""
    number = to_float(value)
    if number is None:
        return None
    return int(number) if number.is_integer() and "." not in str(value) else number


def to_bool(value):
    if value in (None, "", "$undefined"):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def positive_id(value):
    """An id, or None for the upstream's 0 / "" placeholders."""
    number = to_int(value)
    return number if number else None


def iso_time(ms):
    """Epoch milliseconds (int or numeric string) -> ISO-8601 UTC."""
    number = to_float(ms)
    if not number:
        return None
    if number > 1e11:          # milliseconds
        number /= 1000.0
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def iso_date(ms):
    stamp = iso_time(ms)
    return stamp[:10] if stamp else None


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                       "sep", "oct", "nov", "dec"], start=1)}


def parse_date_text(text):
    """"November 05, 1988 (37 years)" / "19 Jul 26" / "2001-09-07" -> YYYY-MM-DD."""
    text = clean(text)
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if match:
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
    match = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})$", text)
    if match:
        month = _MONTHS.get(match.group(2)[:3].lower())
        year = int(match.group(3))
        if year < 100:
            year += 2000 if year < 70 else 1900
        if month:
            return f"{year:04d}-{month:02d}-{int(match.group(1)):02d}"
    return None


def strip_html(text):
    """Commentary and bios carry <b>/<br> markup; keep the text only."""
    if text is None:
        return None
    text = str(text).replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text).replace("\\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text).strip()
    return text or None


def render_formats(text, formats):
    """Substitute the `B0$` placeholders of the full-commentary feed with
    their `commentaryFormats.bold.formatValue` texts."""
    if not text:
        return None
    values = {}
    for style in (formats or {}).values():
        if not isinstance(style, dict):
            continue
        ids = style.get("formatId") or []
        vals = style.get("formatValue") or []
        for key, val in zip(ids, vals):
            values[key] = val
    if values:
        text = re.sub(r"B\d+\$", lambda m: values.get(m.group(0), ""), text)
    return strip_html(text)


def slugify(text):
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or "x"


# ---- links / images -------------------------------------------------------------------------

def image(image_id):
    image_id = positive_id(image_id)
    return IMG.format(id=image_id) if image_id else None


def match_link(match_id, description=None, team1=None, team2=None, series=None):
    parts = [p for p in (team1, "vs" if team1 and team2 else None, team2, description, series) if p]
    return f"{SITE}/live-cricket-scores/{match_id}/{slugify(' '.join(parts)) if parts else 'match'}"


def series_link(series_id, name=None):
    return f"{SITE}/cricket-series/{series_id}/{slugify(name) if name else 'series'}"


def team_link(team_id, name=None):
    return f"{SITE}/cricket-team/{slugify(name) if name else 'team'}/{team_id}"


def player_link(player_id, name=None):
    return f"{SITE}/profiles/{player_id}/{slugify(name) if name else 'player'}"


def venue_link(venue_id, name=None):
    return f"{SITE}/cricket-venues/{venue_id}/{slugify(name) if name else 'venue'}"


def news_link(news_id, headline=None):
    return f"{SITE}/cricket-news/{news_id}/{slugify(headline) if headline else 'story'}"


def gallery_link(gallery_id, headline=None):
    return f"{SITE}/cricket-gallery/{gallery_id}/{slugify(headline) if headline else 'gallery'}"


def video_link(video_id, title=None):
    return f"{SITE}/cricket-videos/{video_id}/{slugify(title) if title else 'video'}"


def absolute(path):
    if not path:
        return None
    if path.startswith("http"):
        return path
    return SITE + (path if path.startswith("/") else "/" + path)


def id_from_path(path):
    """First numeric segment of a site path (see refs)."""
    for segment in (path or "").split("/"):
        if segment.isdigit():
            return int(segment)
    return None


# ---- entity refs ---------------------------------------------------------------------------------

def team_ref(raw, *, id_key="teamId", name_key="teamName", short_key="teamSName", image_key="imageId"):
    if not isinstance(raw, dict):
        return None
    team_id = positive_id(raw.get(id_key) or raw.get("id"))
    name = clean(raw.get(name_key) or raw.get("name"))
    if not team_id and not name:
        return None
    return {
        "id": team_id,
        "name": name,
        "short_name": clean(raw.get(short_key) or raw.get("shortName")),
        "link": team_link(team_id, name) if team_id else None,
        "flag": image(raw.get(image_key) or raw.get("teamImageId")),
    }


def team_stub(team_id, name=None, short_name=None, image_id=None):
    team_id = positive_id(team_id)
    if not team_id and not clean(name):
        return None
    return {"id": team_id, "name": clean(name), "short_name": clean(short_name),
            "link": team_link(team_id, name) if team_id else None, "flag": image(image_id)}


def player_stub(player_id, name=None, image_id=None):
    player_id = positive_id(player_id)
    name = clean(name)
    if not player_id and not name:
        return None
    return {"id": player_id, "name": name,
            "link": player_link(player_id, name) if player_id else None,
            "image": image(image_id)}


def series_stub(series_id, name=None):
    series_id = positive_id(series_id)
    if not series_id and not clean(name):
        return None
    return {"id": series_id, "name": clean(name),
            "link": series_link(series_id, name) if series_id else None}


def venue_ref(raw):
    if not isinstance(raw, dict):
        return None
    venue_id = positive_id(raw.get("id"))
    name = clean(raw.get("ground") or raw.get("name"))
    if not venue_id and not name:
        return None
    out = {
        "id": venue_id,
        "name": name,
        "city": clean(raw.get("city")),
        "country": clean(raw.get("country")),
        "timezone": clean(raw.get("timezone")),
        "link": venue_link(venue_id, name) if venue_id else None,
    }
    lat, lng = to_float(raw.get("latitude")), to_float(raw.get("longitude"))
    if lat is not None and lng is not None:
        out["coordinates"] = {"latitude": lat, "longitude": lng}
    return out


def official_ref(raw):
    if not isinstance(raw, dict) or not (raw.get("id") or raw.get("name")):
        return None
    return {"id": positive_id(raw.get("id")), "name": clean(raw.get("name")),
            "country": clean(raw.get("country"))}


# ---- match state -------------------------------------------------------------------------------

_COMPLETED_STATES = {"complete", "abandon", "abandoned", "result", "cancelled", "canceled", "no result"}
_UPCOMING_STATES = {"preview", "upcoming", "scheduled"}


def status_category(state):
    """The coarse bucket behind Cricbuzz's many `state` strings."""
    text = (clean(state) or "").lower()
    if not text:
        return None
    if text in _COMPLETED_STATES or text.startswith("abandon"):
        return "completed"
    if text in _UPCOMING_STATES:
        return "upcoming"
    return "live"


def innings_score(raw):
    if not isinstance(raw, dict):
        return None
    return {
        "innings_id": to_int(raw.get("inningsId")),
        "runs": to_int(raw.get("runs") if "runs" in raw else raw.get("score")),
        "wickets": to_int(raw.get("wickets")),
        "overs": to_float(raw.get("overs")),
        "is_declared": to_bool(raw.get("isDeclared")),
        "is_follow_on": to_bool(raw.get("isFollowOn")),
    }


def _team_scores(raw):
    """matchScore.team1Score -> [innings scores] (inngs1, inngs2, ...)."""
    if not isinstance(raw, dict):
        return []
    out = []
    for key in sorted(raw, key=lambda k: to_int(k.replace("inngs", "")) or 0):
        score = innings_score(raw[key])
        if score:
            out.append(score)
    return out


def match_summary(raw):
    """A list-row match ({matchInfo, matchScore}) -> the public summary."""
    if not isinstance(raw, dict):
        return None
    if "matchInfo" not in raw and isinstance(raw.get("match"), dict):
        raw = raw["match"]                      # the home carousel wraps rows once more
    info = raw.get("matchInfo") or raw
    score = raw.get("matchScore") or {}
    match_id = positive_id(info.get("matchId"))
    team1 = team_ref(info.get("team1"))
    team2 = team_ref(info.get("team2"))
    if team1:
        team1["innings"] = _team_scores(score.get("team1Score"))
    if team2:
        team2["innings"] = _team_scores(score.get("team2Score"))
    description = clean(info.get("matchDesc") or info.get("matchDescription"))
    series_name = clean(info.get("seriesName"))
    state = clean(info.get("state"))
    return {
        "id": match_id,
        "description": description,
        "format": clean(info.get("matchFormat")),
        "type": clean(info.get("matchType")),
        "link": match_link(match_id, description,
                           (team1 or {}).get("short_name"), (team2 or {}).get("short_name"),
                           series_name) if match_id else None,
        "state": state,
        "status": clean(info.get("status")),
        "short_status": clean(info.get("shortStatus")),
        "status_category": status_category(state),
        "start_time": iso_time(info.get("startDate")),
        "end_time": iso_time(info.get("endDate")),
        "is_time_announced": to_bool(info.get("isTimeAnnounced")),
        "team1": team1,
        "team2": team2,
        "batting_team_id": positive_id(info.get("currBatTeamId")),
        "series": {
            **(series_stub(info.get("seriesId"), series_name) or {}),
            "start_date": iso_date(info.get("seriesStartDt")),
            "end_date": iso_date(info.get("seriesEndDt")),
            "is_tournament": to_bool(info.get("isTournament")) or False,
            "category": clean(info.get("seriesCategory")),
        },
        "venue": venue_ref(info.get("venueInfo")),
        "image": image(info.get("matchImageId")),
    }


def type_matches(raw):
    """`typeMatches` (the live/recent/upcoming lists) -> [{type, series: [...]}]."""
    groups = []
    for group in (raw or {}).get("typeMatches") or []:
        series_list = []
        for wrapper in group.get("seriesMatches") or []:
            series = wrapper.get("seriesAdWrapper") if isinstance(wrapper, dict) else None
            if not series:
                continue
            matches = [match_summary(m) for m in series.get("matches") or []]
            series_list.append({
                **(series_stub(series.get("seriesId"), series.get("seriesName")) or {}),
                "match_count": len(matches),
                "matches": [m for m in matches if m],
            })
        groups.append({"type": clean(group.get("matchType")), "series": series_list})
    return groups


def schedule_days(raw):
    """`matchScheduleMap` (the schedule page) -> [{date, matches: [...]}]."""
    days = []
    for wrapper in (raw or {}).get("matchScheduleMap") or []:
        day = wrapper.get("scheduleAdWrapper") if isinstance(wrapper, dict) else None
        if not day:
            continue
        matches = []
        for series in day.get("matchScheduleList") or []:
            for info in series.get("matchInfo") or []:
                item = match_summary({"matchInfo": info})
                if not item:
                    continue
                item["series"]["name"] = item["series"]["name"] or clean(series.get("seriesName"))
                item["series"]["id"] = item["series"]["id"] or positive_id(series.get("seriesId"))
                item["series"]["link"] = series_link(item["series"]["id"], item["series"]["name"]) if item["series"]["id"] else None
                item["series"]["category"] = clean(series.get("seriesCategory"))
                matches.append(item)
        days.append({
            "date": iso_date(day.get("longDate")),
            "label": clean(day.get("date")),
            "match_count": len(matches),
            "matches": matches,
        })
    return days


def dated_matches(rows):
    """`matchDetails`/`teamMatchesData` ([{matchDetailsMap: {key, match}}]) -> [{date, matches}]."""
    days = []
    for row in rows or []:
        block = row.get("matchDetailsMap") if isinstance(row, dict) else None
        if not block:
            continue
        matches = [match_summary(m) for m in block.get("match") or []]
        matches = [m for m in matches if m]
        days.append({
            "date": parse_date_text(re.sub(r"^[A-Za-z]{3},\s*", "", block.get("key") or "")),
            "label": clean(block.get("key")),
            "match_count": len(matches),
            "matches": matches,
        })
    return days


# ---- match header / info ---------------------------------------------------------------------------

def _toss(raw):
    if not isinstance(raw, dict) or not raw.get("tossWinnerName"):
        return None
    return {"winner_team_id": positive_id(raw.get("tossWinnerId")),
            "winner_team": clean(raw.get("tossWinnerName")),
            "decision": clean(raw.get("decision"))}


def _result(raw):
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        "type": clean(raw.get("resultType")),
        "winning_team_id": positive_id(raw.get("winningteamId") or raw.get("winningTeamId")),
        "winning_team": clean(raw.get("winningTeam")),
        "margin": to_int(raw.get("winningMargin")),
        "is_by_runs": to_bool(raw.get("winByRuns")),
        "is_by_innings": to_bool(raw.get("winByInnings")),
    }


def _award_player(raw):
    ref = player_stub(raw.get("id"), raw.get("name"), raw.get("faceImageId"))
    if not ref:
        return None
    ref["full_name"] = clean(raw.get("fullName"))
    ref["team"] = clean(raw.get("teamName"))
    ref["is_captain"] = to_bool(raw.get("captain"))
    ref["is_keeper"] = to_bool(raw.get("keeper"))
    return ref


def _innings_order(rows):
    return [{
        "batting_team_id": positive_id(r.get("battingTeamId")),
        "batting_team": clean(r.get("battingTeamShortName")),
        "bowling_team_id": positive_id(r.get("bowlingTeamId")),
        "bowling_team": clean(r.get("bowlingTeamShortName")),
    } for r in rows or [] if isinstance(r, dict)]


def _series_results(raw):
    out = {}
    for key, name in (("testSeriesResult", "test"), ("odiSeriesResult", "odi"), ("t20SeriesResult", "t20")):
        text = clean(raw.get(key))
        if text:
            out[name] = text.strip("'")
    return out or None


def match_header(raw):
    """`matchHeader` (miniscore / scorecard / commentary) -> the public header."""
    if not isinstance(raw, dict):
        return None
    match_id = positive_id(raw.get("matchId"))
    team1 = team_ref(raw.get("team1"), id_key="id", name_key="name", short_key="shortName")
    team2 = team_ref(raw.get("team2"), id_key="id", name_key="name", short_key="shortName")
    description = clean(raw.get("matchDescription"))
    series_name = clean(raw.get("seriesName") or raw.get("seriesDesc"))
    state = clean(raw.get("state"))
    return {
        "id": match_id,
        "description": description,
        "format": clean(raw.get("matchFormat")),
        "type": clean(raw.get("matchType")),
        "link": match_link(match_id, description, (team1 or {}).get("short_name"),
                           (team2 or {}).get("short_name"), series_name) if match_id else None,
        "state": state,
        "status": clean(raw.get("status")),
        "status_category": status_category(state),
        "is_complete": to_bool(raw.get("complete")),
        "is_domestic": to_bool(raw.get("domestic")),
        "is_day_night": to_bool(raw.get("dayNight")),
        "is_covered": None if raw.get("isMatchNotCovered") is None else not to_bool(raw.get("isMatchNotCovered")),
        "has_live_stream": to_bool(raw.get("livestreamEnabled")),
        "year": to_int(raw.get("year")),
        "start_time": iso_time(raw.get("matchStartTimestamp")),
        "end_time": iso_time(raw.get("matchCompleteTimestamp")),
        "toss": _toss(raw.get("tossResults")),
        "result": _result(raw.get("result")),
        "revised_target": (raw.get("revisedTarget") or None) if isinstance(raw.get("revisedTarget"), dict) and raw.get("revisedTarget") else None,
        "players_of_the_match": [p for p in map(_award_player, raw.get("playersOfTheMatch") or []) if p],
        "players_of_the_series": [p for p in map(_award_player, raw.get("playersOfTheSeries") or []) if p],
        "innings_order": _innings_order(raw.get("matchTeamInfo")),
        "team1": team1,
        "team2": team2,
        "series": series_stub(raw.get("seriesId"), series_name),
        "venue": venue_ref(raw.get("venue")),
    }


def match_info(raw):
    """The commentary page's `matchInfo` (officials, series results, toss…)."""
    if not isinstance(raw, dict):
        return None
    header = match_header(raw)
    series = raw.get("series") or {}
    header["series"] = {
        **(series_stub(series.get("id") or raw.get("seriesId"), series.get("name") or raw.get("seriesName")) or {}),
        "start_date": iso_date(series.get("startDate")),
        "end_date": iso_date(series.get("endDate")),
        "is_tournament": to_bool(series.get("tournament")) or False,
        "results": _series_results(series),
    }
    header["short_status"] = clean(raw.get("shortStatus"))
    header["image"] = image(raw.get("matchImageId"))
    header["umpires"] = [u for u in (official_ref(raw.get("umpire1")), official_ref(raw.get("umpire2"))) if u]
    header["third_umpire"] = official_ref(raw.get("umpire3"))
    header["referee"] = official_ref(raw.get("referee"))
    return header


# ---- miniscore --------------------------------------------------------------------------------------

def batter_mini(raw):
    if not isinstance(raw, dict) or not positive_id(raw.get("batId")):
        return None
    return {
        "id": positive_id(raw.get("batId")),
        "name": clean(raw.get("batName")),
        "runs": to_int(raw.get("batRuns")),
        "balls": to_int(raw.get("batBalls")),
        "fours": to_int(raw.get("batFours")),
        "sixes": to_int(raw.get("batSixes")),
        "dots": to_int(raw.get("batDots")),
        "minutes": to_int(raw.get("batMins")),
        "strike_rate": to_float(raw.get("batStrikeRate")),
    }


def bowler_mini(raw):
    if not isinstance(raw, dict) or not positive_id(raw.get("bowlId")):
        return None
    return {
        "id": positive_id(raw.get("bowlId")),
        "name": clean(raw.get("bowlName")),
        "overs": to_float(raw.get("bowlOvs")),
        "maidens": to_int(raw.get("bowlMaidens")),
        "runs": to_int(raw.get("bowlRuns")),
        "wickets": to_int(raw.get("bowlWkts")),
        "economy": to_float(raw.get("bowlEcon")),
        "wides": to_int(raw.get("bowlWides")),
        "no_balls": to_int(raw.get("bowlNoballs")),
    }


def powerplays(raw):
    out = []
    for key in sorted(raw or {}, key=lambda k: to_int(k.split("_")[-1]) or 0):
        pp = raw[key]
        if not isinstance(pp, dict):
            continue
        out.append({"id": to_int(pp.get("ppId")), "type": clean(pp.get("ppType")),
                    "from_over": to_float(pp.get("ppOversFrom")), "to_over": to_float(pp.get("ppOversTo")),
                    "runs": to_int(pp.get("runsScored"))})
    return out


def miniscore(raw):
    """`miniscore` -> the live state of the innings in progress."""
    if not isinstance(raw, dict) or not raw:
        return None
    details = raw.get("matchScoreDetails") or {}
    bat_team = raw.get("batTeam") or {}
    innings = [innings_score(i) for i in details.get("inningsScoreList") or []]
    innings = [i for i in innings if i]
    for entry, src in zip(innings, details.get("inningsScoreList") or []):
        entry["batting_team_id"] = positive_id(src.get("batTeamId"))
        entry["batting_team"] = clean(src.get("batTeamName"))
        entry["balls"] = to_int(src.get("ballNbr"))
    partnership = raw.get("partnerShip") or {}
    return {
        "innings_id": to_int(raw.get("inningsId")),
        "state": clean(details.get("state")),
        "status": clean(raw.get("status") or details.get("customStatus")),
        "batting_team": {"id": positive_id(bat_team.get("teamId")), "runs": to_int(bat_team.get("teamScore")),
                         "wickets": to_int(bat_team.get("teamWkts"))} if bat_team else None,
        "overs": to_float(raw.get("overs")),
        "target": to_int(raw.get("target")) or None,
        "runs_to_win": to_int(raw.get("remRunsToWin")) or None,
        "overs_remaining": to_float(raw.get("oversRem")),
        "current_run_rate": to_float(raw.get("currentRunRate")),
        "required_run_rate": to_float(raw.get("requiredRunRate")) or None,
        "striker": batter_mini(raw.get("batsmanStriker")),
        "non_striker": batter_mini(raw.get("batsmanNonStriker")),
        "bowler": bowler_mini(raw.get("bowlerStriker")),
        "previous_bowler": bowler_mini(raw.get("bowlerNonStriker")),
        "partnership": {"runs": to_int(partnership.get("runs")), "balls": to_int(partnership.get("balls"))} if partnership else None,
        "last_wicket": clean(raw.get("lastWicket")),
        "last_wicket_score": to_int(raw.get("lastWicketScore")),
        "recent_balls": clean(raw.get("recentOvsStats")),
        "recent_performance": [{"label": clean(p.get("label")), "runs": to_int(p.get("runs")), "wickets": to_int(p.get("wkts"))}
                               for p in raw.get("latestPerformance") or [] if isinstance(p, dict)],
        "powerplays": powerplays(raw.get("ppData")),
        "innings": innings,
        "toss": _toss(details.get("tossResults")),
        "event": clean(raw.get("event")),
        "updated_at": iso_time(raw.get("responseLastUpdated")),
    }


# ---- scorecard -----------------------------------------------------------------------------------------

def _ordered(mapping, prefix):
    """{"bat_1": {...}, "bat_2": ...} -> values in key order."""
    if not isinstance(mapping, dict):
        return []
    keys = sorted(mapping, key=lambda k: to_int(k.replace(prefix, "").strip("_")) or 0)
    return [mapping[k] for k in keys if isinstance(mapping[k], dict)]


def scorecard_batter(raw):
    fielders = [positive_id(raw.get(k)) for k in ("fielderId1", "fielderId2", "fielderId3")]
    return {
        "player": {**(player_stub(raw.get("batId"), raw.get("batName")) or {}), "short_name": clean(raw.get("batShortName"))},
        "is_captain": to_bool(raw.get("isCaptain")),
        "is_keeper": to_bool(raw.get("isKeeper")),
        "is_overseas": to_bool(raw.get("isOverseas")),
        "runs": to_int(raw.get("runs")),
        "balls": to_int(raw.get("balls")),
        "fours": to_int(raw.get("fours")),
        "sixes": to_int(raw.get("sixes")),
        "dots": to_int(raw.get("dots")),
        "ones": to_int(raw.get("ones")),
        "twos": to_int(raw.get("twos")),
        "threes": to_int(raw.get("threes")),
        "minutes": to_int(raw.get("mins")),
        "strike_rate": to_float(raw.get("strikeRate")),
        "dismissal": {
            "text": clean(raw.get("outDesc")),
            "type": clean(raw.get("wicketCode")),
            "bowler_id": positive_id(raw.get("bowlerId")),
            "fielder_ids": [f for f in fielders if f],
        } if clean(raw.get("outDesc")) else None,
        "in_match_change": clean(raw.get("inMatchChange")),
        "playing_xi_change": clean(raw.get("playingXIChange")),
    }


def scorecard_bowler(raw):
    return {
        "player": {**(player_stub(raw.get("bowlerId"), raw.get("bowlName")) or {}), "short_name": clean(raw.get("bowlShortName"))},
        "is_captain": to_bool(raw.get("isCaptain")),
        "is_keeper": to_bool(raw.get("isKeeper")),
        "is_overseas": to_bool(raw.get("isOverseas")),
        "overs": to_float(raw.get("overs")),
        "maidens": to_int(raw.get("maidens")),
        "runs": to_int(raw.get("runs")),
        "wickets": to_int(raw.get("wickets")),
        "economy": to_float(raw.get("economy")),
        "balls": to_int(raw.get("balls")),
        "dots": to_int(raw.get("dots")),
        "wides": to_int(raw.get("wides")),
        "no_balls": to_int(raw.get("no_balls")),
        "runs_per_ball": to_float(raw.get("runsPerBall")),
        "in_match_change": clean(raw.get("inMatchChange")),
        "playing_xi_change": clean(raw.get("playingXIChange")),
    }


def _partnership(raw):
    return {
        "batter1": {**(player_stub(raw.get("bat1Id"), raw.get("bat1Name"), raw.get("bat1ImageID")) or {}),
                    "runs": to_int(raw.get("bat1Runs")), "balls": to_int(raw.get("bat1balls")),
                    "fours": to_int(raw.get("bat1fours")), "sixes": to_int(raw.get("bat1sixes"))},
        "batter2": {**(player_stub(raw.get("bat2Id"), raw.get("bat2Name"), raw.get("bat2ImageID")) or {}),
                    "runs": to_int(raw.get("bat2Runs")), "balls": to_int(raw.get("bat2balls")),
                    "fours": to_int(raw.get("bat2fours")), "sixes": to_int(raw.get("bat2sixes"))},
        "runs": to_int(raw.get("totalRuns")),
        "balls": to_int(raw.get("totalBalls")),
    }


def score_details(raw):
    if not isinstance(raw, dict):
        return None
    return {
        "runs": to_int(raw.get("runs")),
        "wickets": to_int(raw.get("wickets")),
        "overs": to_float(raw.get("overs")),
        "balls": to_int(raw.get("ballNbr")),
        "run_rate": to_float(raw.get("runRate")),
        "runs_per_ball": to_float(raw.get("runsPerBall")),
        "revised_overs": to_int(raw.get("revisedOvers")) or None,
        "is_declared": to_bool(raw.get("isDeclared")),
        "is_follow_on": to_bool(raw.get("isFollowOn")),
    }


def scorecard_innings(raw):
    bat = raw.get("batTeamDetails") or {}
    bowl = raw.get("bowlTeamDetails") or {}
    extras = raw.get("extrasData") or {}
    wickets = []
    for w in _ordered(raw.get("wicketsData"), "wkt"):
        wickets.append({
            "wicket_number": to_int(w.get("wktNbr")),
            "player": player_stub(w.get("batId"), w.get("batName")),
            "score": to_int(w.get("wktRuns")),
            "over": to_float(w.get("wktOver")),
            "ball": to_int(w.get("ballNbr")),
        })
    return {
        "innings_id": to_int(raw.get("inningsId")),
        "batting_team": team_stub(bat.get("batTeamId"), bat.get("batTeamName"), bat.get("batTeamShortName")),
        "bowling_team": team_stub(bowl.get("bowlTeamId"), bowl.get("bowlTeamName"), bowl.get("bowlTeamShortName")),
        "score": score_details(raw.get("scoreDetails")),
        "extras": {
            "total": to_int(extras.get("total")), "wides": to_int(extras.get("wides")),
            "no_balls": to_int(extras.get("noBalls")), "byes": to_int(extras.get("byes")),
            "leg_byes": to_int(extras.get("legByes")), "penalty": to_int(extras.get("penalty")),
        } if extras else None,
        "batting": [scorecard_batter(b) for b in _ordered(bat.get("batsmenData"), "bat")],
        "bowling": [scorecard_bowler(b) for b in _ordered(bowl.get("bowlersData"), "bowl")],
        "fall_of_wickets": wickets,
        "partnerships": [_partnership(p) for p in _ordered(raw.get("partnershipsData"), "pat")],
        "powerplays": powerplays(raw.get("ppData")),
        "updated_at": iso_time(raw.get("timeScore")),
    }


def scorecard(raw):
    raw = raw or {}
    return {
        "match": match_header(raw.get("matchHeader")),
        "status": clean(raw.get("status")),
        "is_complete": to_bool(raw.get("isMatchComplete") if "isMatchComplete" in raw else raw.get("matchComplete")),
        "innings": [scorecard_innings(i) for i in raw.get("scoreCard") or [] if isinstance(i, dict)],
        "updated_at": iso_time(raw.get("responseLastUpdated")),
    }


# ---- commentary -----------------------------------------------------------------------------------------

def _events(value):
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").split(",")
    out = []
    for item in items:
        token = clean(item)
        if token and token.lower() not in ("none", "all"):
            out.append(token.lower().replace("_", "-"))
    return out


def _over_summary(raw):
    if not isinstance(raw, dict) or not raw:
        return None
    bat = raw.get("batTeamObj") or {}
    striker = raw.get("batStrikerObj") or {}
    non_striker = raw.get("batNonStrikerObj") or {}
    bowler = raw.get("bowlerObj") or {}
    return {
        "over": to_int(raw.get("overNumber")),
        "balls": clean(raw.get("overSummary")),
        "runs": to_int(raw.get("overRuns")),
        "batting_team": {"name": clean(bat.get("teamName")), "score": clean(bat.get("teamScore"))} if bat else None,
        "striker": {**(player_stub(striker.get("playerId"), striker.get("playerName")) or {}), "score": clean(striker.get("playerScore"))} if striker.get("playerName") else None,
        "non_striker": {**(player_stub(non_striker.get("playerId"), non_striker.get("playerName")) or {}), "score": clean(non_striker.get("playerScore"))} if non_striker.get("playerName") else None,
        "bowler": {**(player_stub(bowler.get("playerId"), bowler.get("playerName")) or {}), "figures": clean(bowler.get("playerScore"))} if bowler.get("playerName") else None,
        "time": iso_time(raw.get("timestamp")),
    }


def commentary_entry(raw):
    """One ball/line of commentary, from either feed shape: the /comm feed
    (`commText` HTML, `ballMetric`, `batsmanDetails`) or the full-commentary
    / highlights feed (`B0$` placeholders, `overNumber`, `batsmanStriker`)."""
    if not isinstance(raw, dict):
        return None
    text = render_formats(raw.get("commText"), raw.get("commentaryFormats"))
    batter = raw.get("batsmanDetails") or {}
    bowler = raw.get("bowlerDetails") or {}
    over = raw.get("ballMetric") if raw.get("ballMetric") is not None else raw.get("overNumber")
    out = {
        "time": iso_time(raw.get("timestamp")),
        "innings_id": to_int(raw.get("inningsId")),
        "over": to_float(over),
        "ball_number": to_int(raw.get("ballNbr")) or None,
        "text": text,
        "events": _events(raw.get("event")),
        "batting_team": clean(raw.get("teamName") or raw.get("batTeamName")),
        "batter": player_stub(batter.get("playerId"), batter.get("playerName")) or batter_mini(raw.get("batsmanStriker")),
        "bowler": player_stub(bowler.get("playerId"), bowler.get("playerName")) or bowler_mini(raw.get("bowlerStriker")),
    }
    if "totalRuns" in raw or "legalRuns" in raw:
        out["runs"] = to_int(raw.get("totalRuns"))
        out["legal_runs"] = to_int(raw.get("legalRuns"))
        out["team_score"] = to_int(raw.get("batTeamScore"))
    summary = _over_summary(raw.get("overSeparator"))
    if summary:
        out["over_summary"] = summary
    return out


def commentary_feed(raw):
    """`matchCommentary` ({timestamp: entry} or [entry]) -> newest first."""
    if isinstance(raw, dict):
        items = [raw[k] for k in sorted(raw, key=lambda k: -(to_int(k) or 0))]
    else:
        items = list(raw or [])
    out = [commentary_entry(i) for i in items]
    return [i for i in out if i and (i["text"] or i["over"] is not None)]


def commentary_list(raw):
    out = [commentary_entry(i) for i in raw or []]
    return [i for i in out if i and (i["text"] or i["over"] is not None)]


# ---- overs / balls / partnerships --------------------------------------------------------------------------

def _first(values):
    return values[0] if isinstance(values, list) and values else values


def over_summary(raw):
    return {
        "innings_id": to_int(raw.get("inningsId")),
        "over": to_int(raw.get("overs")),
        "runs": to_int(raw.get("runs")),
        "balls": clean(raw.get("ovrSummary")),
        "score": to_int(raw.get("score")),
        "wickets": to_int(raw.get("wickets")),
        "batting_team": clean(raw.get("batTeamName")),
        "event": clean(raw.get("event")),
        "striker": {**(player_stub(_first(raw.get("batStrikerIds")), _first(raw.get("batStrikerNames"))) or {}),
                    "runs": to_int(raw.get("batStrikerRuns")), "balls": to_int(raw.get("batStrikerBalls"))},
        "non_striker": {**(player_stub(_first(raw.get("batNonStrikerIds")), _first(raw.get("batNonStrikerNames"))) or {}),
                        "runs": to_int(raw.get("batNonStrikerRuns")), "balls": to_int(raw.get("batNonStrikerBalls"))},
        "bowler": {**(player_stub(_first(raw.get("bowlIds")), _first(raw.get("bowlNames"))) or {}),
                   "overs": to_float(raw.get("bowlOvers")), "maidens": to_int(raw.get("bowlMaidens")),
                   "runs": to_int(raw.get("bowlRuns")), "wickets": to_int(raw.get("bowlWickets"))},
        "time": iso_time(raw.get("timestamp")),
    }


def ball(raw):
    return {
        "innings_id": to_int(raw.get("inningsId")),
        "over": to_float(raw.get("overNum")),
        "ball_number": to_int(raw.get("ballNbr")),
        "runs": to_int(raw.get("totalRuns")),
        "label": clean(raw.get("ballLabel")),
        "events": _events(raw.get("event")),
        "batter_id": positive_id(raw.get("batsmanStrikerId")),
        "bowler_id": positive_id(raw.get("bowlerStrikerId")),
        "time": iso_time(raw.get("timestamp")),
    }


def balls_map(raw):
    raw = raw or {}
    return {
        "score": score_details(raw.get("scoreDetails")),
        "batters": [{**(player_stub(b.get("batId"), b.get("batName")) or {}), "runs": to_int(b.get("runs")),
                     "balls": to_int(b.get("balls")), "dots": to_int(b.get("dots")), "fours": to_int(b.get("fours")),
                     "sixes": to_int(b.get("sixes")), "strike_rate": to_float(b.get("strikeRate"))}
                    for b in raw.get("batters") or [] if isinstance(b, dict)],
        "bowlers": [{**(player_stub(b.get("bowlerId"), b.get("bowlName")) or {}), "overs": to_float(b.get("overs")),
                     "maidens": to_int(b.get("maidens")), "runs": to_int(b.get("runs")), "wickets": to_int(b.get("wickets")),
                     "economy": to_float(b.get("economy")), "wides": to_int(b.get("wides")), "no_balls": to_int(b.get("no_balls"))}
                    for b in raw.get("bowlers") or [] if isinstance(b, dict)],
        "ball_count": len(raw.get("balls") or []),
        "balls": [ball(b) for b in raw.get("balls") or [] if isinstance(b, dict)],
    }


def partnership_graph(raw):
    out = []
    for innings in raw or []:
        if not isinstance(innings, dict):
            continue
        out.append({
            "innings_id": to_int(innings.get("inningsID") or innings.get("inningsId")),
            "batting_team": team_stub(innings.get("batTeamId"), innings.get("batTeamName"), innings.get("batTeamShortName")),
            "partnerships": [_partnership(p) for p in innings.get("partnershipDataDTO") or [] if isinstance(p, dict)],
        })
    return out


# ---- squads ----------------------------------------------------------------------------------------------------

def squad_player(raw):
    if not isinstance(raw, dict):
        return None
    ref = player_stub(raw.get("id"), raw.get("name"), (raw.get("imageDetails") or {}).get("imageId") or raw.get("faceImageId") or raw.get("imageId"))
    if not ref:
        return None
    return {
        **ref,
        "full_name": clean(raw.get("fullName")),
        "nick_name": clean(raw.get("nickName")),
        "role": clean(raw.get("role")),
        "is_captain": to_bool(raw.get("captain")),
        "is_keeper": to_bool(raw.get("keeper")),
        "is_substitute": to_bool(raw.get("substitute")),
        "is_overseas": to_bool(raw.get("isOverseas")),
        "batting_style": clean(raw.get("battingStyle")),
        "bowling_style": clean(raw.get("bowlingStyle")),
        "playing_xi_change": clean(raw.get("playingXIChange")),
        "in_match_change": clean(raw.get("inMatchChange")),
    }


def match_squads(raw):
    """The squads page's {team1: {team, players: {"playing XI", bench, "support staff"}}, team2}."""
    out = {}
    for key in ("team1", "team2"):
        side = (raw or {}).get(key) or {}
        team = side.get("team") or {}
        groups = side.get("players") or {}
        entry = team_ref(team, image_key="imageId")
        if entry is None and team:
            entry = {}
        if entry is not None:
            entry["flag"] = image((team.get("imageDetails") or {}).get("imageId")) or entry.get("flag")
            for group, name in refs.SQUAD_GROUPS.items():
                entry[name] = [p for p in map(squad_player, groups.get(group) or []) if p]
        out[key] = entry
    return out


def series_squad_players(raw):
    """/api/cricket-series/series-squads: a flat list with header rows."""
    groups = []
    current = None
    for item in (raw or {}).get("player") or []:
        if not isinstance(item, dict):
            continue
        if item.get("isHeader"):
            current = {"group": clean(item.get("name")), "players": []}
            groups.append(current)
            continue
        player = player_stub(item.get("id"), item.get("name"), item.get("imageId"))
        if not player:
            continue
        player.update({"role": clean(item.get("role")), "batting_style": clean(item.get("battingStyle")),
                       "bowling_style": clean(item.get("bowlingStyle")),
                       "is_captain": to_bool(item.get("captain")), "is_keeper": to_bool(item.get("keeper"))})
        if current is None:
            current = {"group": None, "players": []}
            groups.append(current)
        current["players"].append(player)
    return groups


# ---- tables (records, stats, rankings) ----------------------------------------------------------------------------

HEADER_KEYS = {
    "player": "player", "team": "team", "matches": "matches", "inns": "innings", "runs": "runs",
    "avg": "average", "sr": "strike_rate", "4s": "fours", "6s": "sixes", "hs": "highest_score",
    "bf": "balls_faced", "balls": "balls", "100s": "hundreds", "50s": "fifties", "90s": "nineties",
    "no": "not_outs", "overs": "overs", "wkts": "wickets", "econ": "economy", "bbi": "best_bowling_innings",
    "bbm": "best_bowling_match", "4-fers": "four_wicket_hauls", "5-fers": "five_wicket_hauls",
    "5w": "five_wicket_hauls", "10w": "ten_wicket_hauls", "maidens": "maidens", "mdns": "maidens",
    "ducks": "ducks", "dots": "dots", "d": "dots", "b": "balls", "r": "runs", "bowler": "bowler",
    "score": "score", "oppn.": "opponent", "format": "format", "date": "date", "venue": "venue",
    "wickets": "wickets", "stats": "stat", "ranking": "rank", "rank": "rank", "rating": "rating",
    "points": "points", "2s": "twos", "1s": "ones", "3s": "threes", "st": "stumpings", "ct": "catches",
    "runs conceded": "runs_conceded", "against": "opponent", "opponent": "opponent",
    "eco": "economy", "4w": "four_wicket_hauls", "highest": "highest_score", "not out": "not_outs",
    "200s": "double_hundreds", "300s": "triple_hundreds", "400s": "quadruple_hundreds",
}


def header_key(header):
    text = clean(header) or ""
    key = HEADER_KEYS.get(text.lower())
    if key:
        return key
    return _SLUG_RE.sub("_", text.lower()).strip("_") or "value"


def _cell(value):
    number = to_number(value)
    if number is not None and not str(value).startswith("+") and not re.fullmatch(r"\d+\(\d+\)", str(value)):
        return number
    return clean(value)


def table_rows(headers, rows, *, entity=None):
    """[headers] + [[cells]] -> [dict]. When the first column is a player or
    team, the upstream prepends the entity id to each row (one more cell
    than headers) — that pair becomes `player`/`team`: {id, name, link}."""
    headers = [header_key(h) for h in headers or []]
    out = []
    for row in rows or []:
        cells = row.get("values") if isinstance(row, dict) else row
        if not isinstance(cells, list):
            continue
        cells = list(cells)
        record = {}
        extra = {}
        if isinstance(row, dict):
            if row.get("followUpLinkText"):
                extra["match_id"] = id_from_path(row.get("followUpLinkText"))
                extra["match_link"] = absolute(row.get("followUpLinkText"))
            if row.get("seriesId"):
                extra["series_id"] = to_int(row.get("seriesId"))
        kind = entity or (headers[0] if headers and headers[0] in ("player", "team", "bowler") else None)
        if kind == "match" and len(cells) == len(headers) + 1:
            extra.setdefault("match_id", to_int(cells[0]))
            extra.setdefault("match_link", match_link(to_int(cells[0])) if to_int(cells[0]) else None)
            cells = cells[1:]
            keys = headers
        elif kind and len(cells) == len(headers) + 1:
            entity_id, name = cells[0], cells[1]
            cells = cells[2:]
            keys = headers[1:]
            if kind == "team":
                record["team"] = team_stub(entity_id, name)
            else:
                record[kind] = player_stub(entity_id, name)
        else:
            keys = headers
        for key, value in zip(keys, cells):
            record[key] = parse_date_text(value) or clean(value) if key == "date" else _cell(value)
        record.update(extra)
        out.append(record)
    return out


def key_value_table(rows):
    """[{values: ["Matches", "123", "314", ...]}] with column headers ->
    {column: {row: value}} (the profile's per-format stat tables)."""
    return rows


def stats_table(raw, *, entity="player"):
    """/api/cricket-stats/stats-table and the team/series stats tabs."""
    raw = raw or {}
    headers = raw.get("webHeaders") or raw.get("headers") or []
    values = raw.get("webValues") or raw.get("values") or []
    return {
        "headers": [clean(h) for h in headers],
        "rows": table_rows(headers, values, entity=entity),
        "filters": {
            "formats": [{"id": clean(f.get("matchTypeId")), "name": clean(f.get("matchTypeDesc"))}
                        for f in raw.get("matchTypes") or [] if isinstance(f, dict)] or None,
            "teams": [{"id": clean(t.get("id")), "short_name": clean(t.get("teamShortName"))}
                      for t in raw.get("teams") or [] if isinstance(t, dict)] or None,
            "opponents": [{"id": clean(t.get("id")), "short_name": clean(t.get("teamShortName"))}
                          for t in raw.get("opponentTeams") or [] if isinstance(t, dict)] or None,
            "years": [clean(y) for y in raw.get("years") or []] or None,
        },
    }


def stats_types(raw):
    """{"Batting": [{value, header}], "Bowling": [...]} or the series list form."""
    out = []
    if isinstance(raw, dict):
        for category, items in raw.items():
            for item in items or []:
                if isinstance(item, dict) and item.get("value"):
                    out.append({"stats_type": refs.stats_type_public(item["value"]), "name": clean(item.get("header")),
                                "category": clean(item.get("category") or category)})
    elif isinstance(raw, list):
        category = None
        for item in raw:
            if not isinstance(item, dict):
                continue
            if not item.get("value"):
                category = clean(item.get("header"))
                continue
            out.append({"stats_type": refs.stats_type_public(item["value"]), "name": clean(item.get("header")),
                        "category": clean(item.get("category") or category)})
    return out


def ranking_row(raw, *, teams=False):
    entity_id = positive_id(raw.get("id"))
    name = clean(raw.get("name"))
    out = {
        "rank": to_int(raw.get("rank")),
        "id": entity_id,
        "name": name,
        "link": (team_link(entity_id, name) if teams else player_link(entity_id, name)) if entity_id else None,
        "rating": to_int(raw.get("rating")),
        "points": to_int(raw.get("points")),
        "trend": clean(raw.get("trend")),
    }
    if teams:
        out["matches"] = to_int(raw.get("matches"))
        out["flag"] = image(raw.get("imageId"))
    else:
        out["country"] = clean(raw.get("country"))
        out["image"] = image(raw.get("faceImageId") or raw.get("imageId"))
    return out


# ---- points tables / standings ----------------------------------------------------------------------------------

def _team_match(raw):
    opponent = team_stub(raw.get("opponentId"), raw.get("opponent"), raw.get("opponentSName"), raw.get("opponentImageId"))
    winner = positive_id(raw.get("winner"))
    return {
        "match_id": positive_id(raw.get("matchId")),
        "name": clean(raw.get("matchName")),
        "link": match_link(positive_id(raw.get("matchId"))) if positive_id(raw.get("matchId")) else None,
        "opponent": opponent,
        "result": clean(raw.get("result")),
        "is_win": (winner != (opponent or {}).get("id")) if winner else None,
        "net_run_rate_change": to_float(raw.get("nrrChanges")),
        "start_time": iso_time(raw.get("startdt")),
    }


def points_table(raw):
    raw = raw or {}
    groups = []
    for group in raw.get("pointsTable") or []:
        teams = []
        for row in group.get("pointsTableInfo") or []:
            teams.append({
                "team": team_stub(row.get("teamId"), row.get("teamFullName") or row.get("teamName"),
                                  row.get("teamName"), row.get("teamImageId")),
                "played": to_int(row.get("matchesPlayed")),
                "won": to_int(row.get("matchesWon")),
                "lost": to_int(row.get("matchesLost")),
                "tied": to_int(row.get("matchesTied")),
                "drawn": to_int(row.get("matchesDrawn")),
                "no_result": to_int(row.get("noRes")),
                "points": to_int(row.get("points")),
                "net_run_rate": to_float(row.get("nrr")),
                "form": [clean(f) for f in row.get("form") or [] if clean(f)],
                "qualify_status": clean(row.get("teamQualifyStatus")),
                "matches": [_team_match(m) for m in row.get("teamMatches") or [] if isinstance(m, dict)],
            })
        groups.append({"name": clean(group.get("groupName")), "qualifying_spots": to_int(group.get("no_of_qual")),
                       "teams": teams})
    return {
        "series": series_stub(raw.get("seriesId"), raw.get("seriesName")),
        "format": clean(raw.get("match_type")),
        "legend": {clean(l.get("key")): clean(l.get("value")) for l in raw.get("legends") or [] if isinstance(l, dict) and clean(l.get("key"))} or None,
        "rules": [{"title": clean(r.get("header")), "lines": [clean(v) for v in r.get("values") or [] if clean(v)]}
                  for r in raw.get("tournamentRules") or [] if isinstance(r, dict)],
        "groups": groups,
        "updated_at": iso_time(raw.get("lastUpdated")),
    }


def icc_standings(raw, format_name=None):
    raw = raw or {}
    seasons = [{"id": to_int(s.get("id")), "name": clean(s.get("name")), "start_year": to_int(s.get("startYear")),
                "end_year": to_int(s.get("endYear")), "is_active": to_bool(s.get("isActive"))}
               for s in raw.get("seasonStandings") or [] if isinstance(s, dict)]
    teams = []
    for row in raw.get("teamStandings") or []:
        if not isinstance(row, dict):
            continue
        teams.append({
            "rank": to_int(row.get("teamRank")),
            "team": team_stub(row.get("teamId"), row.get("teamName"), None, row.get("teamImageId")),
            "played": to_int(row.get("matchesPlayed")),
            "won": to_int(row.get("matchesWon")),
            "lost": to_int(row.get("matchesLost")),
            "drawn": to_int(row.get("matchesDrawn")),
            "tied": to_int(row.get("matchesTied")),
            "series_played": to_float(row.get("seriesPlayed")),
            "points": to_int(row.get("totalPoints")),
            "percentage": to_float(row.get("pctPercentage")),
            "is_currently_playing": to_bool(row.get("currentlyPlaying")),
            "season_id": to_int(row.get("seasonId")),
        })
    return {"format": format_name, "seasons": seasons, "note": clean(raw.get("subText")), "teams": teams}


# ---- players -------------------------------------------------------------------------------------------------------

def _stat_table(raw):
    """{headers: [ROWHEADER, Test, ODI, ...], values: [{values: [Matches, 1, 2, ...]}]} ->
    {test: {matches: 1, ...}, odi: {...}}."""
    if not isinstance(raw, dict):
        return None
    headers = [clean(h) for h in raw.get("headers") or []]
    if not headers:
        return None
    columns = {h.lower(): {} for h in headers[1:] if h}
    for row in raw.get("values") or []:
        cells = row.get("values") if isinstance(row, dict) else row
        if not isinstance(cells, list) or not cells:
            continue
        key = header_key(cells[0])
        for header, value in zip(headers[1:], cells[1:]):
            if header:
                columns[header.lower()][key] = _cell(value)
    return columns or None


def _rankings(raw):
    if not isinstance(raw, dict):
        return None
    out = {}
    for key, name in (("bat", "batting"), ("bowl", "bowling"), ("all", "all_rounder")):
        block = raw.get(key)
        if not isinstance(block, dict) or not block:
            continue
        formats = {}
        for fmt in ("test", "odi", "t20"):
            current = to_int(block.get(f"{fmt}Rank"))
            best = to_int(block.get(f"{fmt}BestRank"))
            if current or best:
                formats[fmt] = {"current": current, "best": best}
        if formats:
            out[name] = formats
    return out or None


def _age(text):
    match = re.search(r"\((\d+)\s*years?\)", text or "")
    return int(match.group(1)) if match else None


def player_profile(data, bio=None):
    """The profile page's {playerData, battingStats, bowlingStats, playerCareerData, playerNews}."""
    data = data or {}
    p = data.get("playerData") or {}
    player_id = positive_id(p.get("id"))
    name = clean(p.get("name"))
    career = []
    for row in ((data.get("playerCareerData") or {}).get("values") or []):
        if not isinstance(row, dict):
            continue
        career.append({
            "format": clean(row.get("name")),
            "debut": {"text": clean(row.get("debut")), "match_id": positive_id(row.get("debutMatchID"))},
            "last_played": {"text": clean(row.get("lastPlayed")), "match_id": positive_id(row.get("lastPlayedMatchId"))},
        })
    teams = [team_stub(t.get("teamId"), t.get("teamName")) for t in p.get("teamNameIds") or [] if isinstance(t, dict)]
    return {
        "id": player_id,
        "name": name,
        "full_name": clean(p.get("fullName")),
        "link": player_link(player_id, name) if player_id else None,
        "image": image(p.get("faceImageId")),
        "role": clean(p.get("role")),
        "batting_style": clean(p.get("bat")),
        "bowling_style": clean(p.get("bowl")),
        "height": clean(p.get("height")),
        "birth_place": clean(p.get("birthPlace")),
        "date_of_birth": parse_date_text(p.get("DoBFormat") or p.get("DoB")),
        "age": _age(p.get("DoB")),
        "international_team": {"name": clean(p.get("intlTeam")), "flag": image(p.get("intlTeamImageId"))} if clean(p.get("intlTeam")) else None,
        "teams": [t for t in teams if t],
        "rankings": _rankings(p.get("rankings")),
        "batting_stats": _stat_table(data.get("battingStats")),
        "bowling_stats": _stat_table(data.get("bowlingStats")),
        "career": career,
        "recent_batting": table_rows((p.get("recentBatting") or {}).get("headers"), (p.get("recentBatting") or {}).get("rows"), entity="match"),
        "recent_bowling": table_rows((p.get("recentBowling") or {}).get("headers"), (p.get("recentBowling") or {}).get("rows"), entity="match"),
        "bio": strip_html(bio),
        "news": [story(s) for s in ((data.get("playerNews") or {}).get("storyList") or []) if isinstance(s, dict) and s.get("story")],
    }


def search_player(raw):
    ref = player_stub(raw.get("id"), raw.get("name"), raw.get("faceImageId"))
    if not ref:
        return None
    ref["team"] = clean(raw.get("teamName"))
    ref["date_of_birth"] = parse_date_text(raw.get("dob"))
    return ref


def player_form(raw):
    raw = raw or {}
    filters = []
    for f in raw.get("filters") or []:
        if isinstance(f, dict):
            filters.append({"key": clean(f.get("value")), "label": clean(f.get("label")),
                            "options": [{"value": clean(o.get("value")), "label": clean(o.get("label")), "short_name": clean(o.get("shortName"))}
                                        for o in f.get("options") or [] if isinstance(o, dict)]})
    series = {to_int(s.get("seriesID")): clean(s.get("seriesName")) for s in raw.get("seriesMap") or [] if isinstance(s, dict)}
    rows = table_rows(raw.get("headers"), raw.get("rows"), entity="match")
    for row in rows:
        series_id = row.pop("series_id", None)
        if series_id:
            row["series"] = series_stub(series_id, series.get(series_id))
    return {
        "player": player_stub(raw.get("playerID"), raw.get("playerName"), raw.get("playerImageID")),
        "summary": table_rows((raw.get("summary") or {}).get("headers"), [(raw.get("summary") or {}).get("values")]) if (raw.get("summary") or {}).get("values") else None,
        "headers": [clean(h) for h in raw.get("headers") or []],
        "innings": rows,
        "series": [series_stub(k, v) for k, v in series.items() if k],
        "filters": filters,
        "note": clean(raw.get("disclaimer")),
        "next_date": clean(raw.get("nextDate")),
        "page": to_int(raw.get("pageNumber")),
    }


def player_performance(raw):
    """The player-match-performance page's initialData."""
    raw = raw or {}
    header = raw.get("header") or {}
    player = header.get("player") or {}
    out = {
        "player": {**(player_stub(player.get("id"), player.get("name"), player.get("imageId")) or {}), "role": clean(player.get("role"))},
        "batting_summary": clean(header.get("battingSummary")),
        "bowling_summary": clean(header.get("bowlingSummary")),
    }
    for key, name in (("battingDetails", "batting"), ("bowlingDetails", "bowling")):
        block = raw.get(key)
        if not isinstance(block, dict):
            out[name] = None
            continue
        innings = []
        for inn in block.get("innings") or []:
            card = inn.get("card") or {}
            matchups = inn.get("matchups") or {}
            innings.append({
                "innings_id": to_int(inn.get("inningsId")),
                "label": clean(inn.get("inningsLabel")),
                "dismissed_by_id": positive_id(inn.get("wicketBowlerId")),
                "summary": dict(zip([header_key(h) for h in card.get("headers") or []], [_cell(v) for v in card.get("values") or []])) or None,
                "matchups": table_rows(matchups.get("headers"), matchups.get("values"), entity="bowler" if name == "batting" else "player"),
                "commentary": commentary_list(inn.get("commentaryList")),
            })
        stats = block.get("seriesStats") or {}
        details = stats.get("details") or {}
        overall = stats.get("overall") or {}
        out[name] = {
            "innings": innings,
            "series_stats": {
                "series": {**(series_stub(details.get("seriesId"), details.get("seriesName")) or {}), "format": clean(details.get("format"))},
                "stats": [{"stat": clean(r[0]) if r else None, "value": _cell(r[1]) if len(r) > 1 else None,
                           "rank": _cell(r[2]) if len(r) > 2 else None} for r in overall.get("values") or [] if isinstance(r, list)],
            } if stats else None,
        }
    return out


# ---- teams ---------------------------------------------------------------------------------------------------------

def team_info(raw):
    raw = raw or {}
    ref = team_ref(raw)
    if not ref:
        return None
    ref.update({
        "is_full_member": to_bool(raw.get("isFullMember")),
        "is_active": to_bool(raw.get("isActive")),
    })
    return ref


# ---- series ----------------------------------------------------------------------------------------------------------

def series_info(raw):
    raw = raw or {}
    ref = series_stub(raw.get("id"), raw.get("name"))
    if not ref:
        return None
    ref.update({
        "short_name": clean(raw.get("shortName")),
        "category": clean(raw.get("seriesCategory")),
        "start_date": iso_date(raw.get("startDt")),
        "end_date": iso_date(raw.get("endDt")),
        "match_counts": {k: to_int(raw.get(f"{k}Count")) for k in ("test", "odi", "t20") if raw.get(f"{k}Count")} or None,
    })
    return ref


def archive_years(raw):
    out = []
    for block in (raw or {}).get("seriesMapProto") or []:
        series_list = []
        for s in block.get("series") or []:
            item = series_stub(s.get("id"), s.get("name"))
            if not item:
                continue
            item.update({"start_date": iso_date(s.get("startDt")), "end_date": iso_date(s.get("endDt")),
                         "image": None if to_bool(s.get("isDefaultImage")) else image(s.get("thumborImageId"))})
            series_list.append(item)
        out.append({"year": clean(block.get("date")), "series_count": len(series_list), "series": series_list})
    return out


def series_squads(raw):
    groups = []
    current = None
    for item in (raw or {}).get("squads") or []:
        if not isinstance(item, dict):
            continue
        if item.get("isHeader"):
            current = {"format": clean(item.get("squadType")), "squads": []}
            groups.append(current)
            continue
        if current is None:
            current = {"format": None, "squads": []}
            groups.append(current)
        current["squads"].append({"squad_id": to_int(item.get("squadId")),
                                  "team": team_stub(item.get("teamId"), item.get("squadType"), None, item.get("imageId"))})
    return groups


def series_venue(raw):
    ref = venue_ref(raw)
    if ref:
        ref["image"] = image(raw.get("imageId"))
    return ref


# ---- venues ---------------------------------------------------------------------------------------------------------

def _venue_record(raw):
    return {
        "team": team_stub((raw.get("team") or {}).get("id"), (raw.get("team") or {}).get("name"), (raw.get("team") or {}).get("shortName")),
        "opponent": team_stub((raw.get("opponent") or {}).get("id"), (raw.get("opponent") or {}).get("name"), (raw.get("opponent") or {}).get("shortName")),
        "runs": to_int(raw.get("runs")),
        "wickets": to_int(raw.get("wickets")),
        "overs": to_float(raw.get("overs")),
        "match_id": positive_id(raw.get("matchId")),
        "date": parse_date_text(raw.get("startdt")),
    }


def _venue_format_stats(raw):
    if not isinstance(raw, dict) or not raw.get("totalMatches"):
        return None
    return {
        "matches": to_int(raw.get("totalMatches")),
        "won_batting_first": to_int(raw.get("batFirstWon")),
        "won_bowling_first": to_int(raw.get("bowlFirstWon")),
        "average_scores": {k: to_int(raw.get(v)) for k, v in (("first_innings", "avgFirstInnsScore"), ("second_innings", "avgSecondInnsScore"),
                                                             ("third_innings", "avgThirdInnsScore"), ("fourth_innings", "avgFourthInnsScore")) if to_int(raw.get(v)) is not None} or None,
        "highest_totals": [_venue_record(r) for r in raw.get("teamHs") or [] if isinstance(r, dict)],
        "lowest_totals": [_venue_record(r) for r in raw.get("teamLs") or [] if isinstance(r, dict)],
        "highest_chased": [_venue_record(r) for r in raw.get("hsChased") or [] if isinstance(r, dict)],
        "lowest_defended": [_venue_record(r) for r in raw.get("lsDefended") or [] if isinstance(r, dict)],
    }


def venue_details(raw, venue_id):
    raw = raw or {}
    d = raw.get("venueDetails") or {}
    name = clean(d.get("ground"))
    return {
        "id": venue_id,
        "name": name,
        "city": clean(d.get("city")),
        "country": clean(d.get("country")),
        "timezone": clean(d.get("timezone")),
        "link": venue_link(venue_id, name),
        "image": image(d.get("imageId")),
        "capacity": to_int(d.get("capacity")),
        "known_as": clean(d.get("knownAs")),
        "ends": [clean(e) for e in (d.get("ends") or "").split(",") if clean(e)],
        "home_teams": [clean(t) for t in (d.get("homeTeam") or "").split(",") if clean(t)],
        "has_floodlights": to_bool(d.get("floodlights")),
        "stats": {
            "test": _venue_format_stats(raw.get("venueTestStats")),
            "odi": _venue_format_stats(raw.get("venueOdiStats")),
            "t20": _venue_format_stats(raw.get("venueT20Stats")),
        },
    }


# ---- graphs -----------------------------------------------------------------------------------------------------------

def _graph_points(rows):
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.append({
            "over": to_int(r.get("over")),
            "team1": to_number(r.get("team1")),
            "team2": to_number(r.get("team2")),
            "is_team1_wicket": to_bool(r.get("isTeam1Wicket")),
            "is_team2_wicket": to_bool(r.get("isTeam2Wicket")),
            "team1_wicket_commentary": [strip_html(c) for c in r.get("team1WicketCommentary") or [] if c] or None,
            "team2_wicket_commentary": [strip_html(c) for c in r.get("team2WicketCommentary") or [] if c] or None,
            "draw": to_number(r.get("draw")) if "draw" in r else None,
        })
    return out


def match_graphs(raw):
    raw = raw or {}
    data = raw.get("data") or {}
    legends = data.get("winProbabilityChartLegends") or {}
    innings = [{
        "innings_id": to_int(i.get("inningsId")),
        "team": team_stub(i.get("teamId"), i.get("teamName"), i.get("teamShortName")),
        "label": clean(i.get("label")),
        "color": clean((i.get("teamColor") or "").split("|")[0]),
    } for i in data.get("innings") or [] if isinstance(i, dict)]
    win = data.get("winProbabilityChartData") or {}
    return {
        "team1": {**(team_ref((legends.get("team1") or {}).get("team")) or {}), "color": clean(raw.get("team1Color"))},
        "team2": {**(team_ref((legends.get("team2") or {}).get("team")) or {}), "color": clean(raw.get("team2Color"))},
        "innings": innings,
        "runs": _graph_points(data.get("runsChartData")),
        "run_rate": _graph_points(data.get("runRateChartData")),
        "runs_per_over": _graph_points(data.get("runsPerOverChartData")),
        "win_probability": {str(k): _graph_points(v) for k, v in win.items()} if isinstance(win, dict) else None,
        "wicket_overs": [to_int(w) for w in data.get("wicketOvers") or []],
    }


# ---- content: news / photos / videos ----------------------------------------------------------------------------------

def story(raw):
    """{story: {...}} or a bare story dict (series/team/player news feeds)."""
    s = raw.get("story") if isinstance(raw, dict) and isinstance(raw.get("story"), dict) else raw
    if not isinstance(s, dict):
        return None
    news_id = positive_id(s.get("id"))
    headline = clean(s.get("hline") or s.get("headline"))
    cover = s.get("coverImage") or {}
    entitlements = s.get("entitlements") or {}
    return {
        "id": news_id,
        "headline": headline,
        "seo_headline": clean(s.get("seoHeadline")),
        "intro": clean(s.get("intro")),
        "context": clean(s.get("context")),
        "link": news_link(news_id, headline) if news_id else None,
        "image": image(s.get("imageId") or (s.get("imageDetails") or {}).get("imageId")),
        "type": clean(s.get("storyType")),
        "source": clean(s.get("source")),
        "published_at": iso_time(s.get("pubTime")),
        "published_ago": clean(s.get("publishedTime")) if not to_float(s.get("publishedTime")) else None,
        "is_premium": to_bool(s.get("isCbPlusContent")) or bool(entitlements),
        "is_premium_free": to_bool(s.get("isPremiumFree")),
        "cover_image": {"image": image(cover.get("id")), "caption": clean(cover.get("caption")), "credit": clean(cover.get("source"))} if cover else None,
    }


def gallery_summary(raw):
    g = raw.get("photoGalleryInfo") if isinstance(raw, dict) and raw.get("photoGalleryInfo") else raw
    if not isinstance(g, dict):
        return None
    gallery_id = positive_id(g.get("galleryId"))
    headline = clean(g.get("headline"))
    return {"id": gallery_id, "headline": headline, "link": gallery_link(gallery_id, headline) if gallery_id else None,
            "image": image(g.get("imageId")), "published_at": iso_time(g.get("publishedTime"))}


def video_card(raw):
    if not isinstance(raw, dict):
        return None
    video_id = positive_id(raw.get("id"))
    title = clean(raw.get("title"))
    return {
        "id": video_id,
        "title": title,
        "link": absolute(raw.get("onCardClick")) if raw.get("onCardClick") else (video_link(video_id, title) if video_id else None),
        "image": image((raw.get("imageObj") or {}).get("imageId") or raw.get("imageId")),
        "duration": clean(raw.get("durationStr")),
        "published_ago": clean(raw.get("description")),
        "is_premium": to_bool(raw.get("isCbPlusContent")),
        "is_premium_free": to_bool(raw.get("isPremiumFree")),
        "is_live": to_bool(raw.get("isLive")),
        "is_playlist": to_bool(raw.get("isPlayListContent")),
    }


def video_collections(raw):
    out = []
    for c in (raw.get("collections") or []) if isinstance(raw, dict) else (raw or []):
        if not isinstance(c, dict):
            continue
        videos = [v for v in map(video_card, c.get("contentData") or []) if v]
        out.append({"id": to_int(c.get("id")), "name": clean(c.get("label")), "link": absolute(c.get("onMoreContentClick")),
                    "video_count": len(videos), "videos": videos})
    return out


def video_details(raw):
    if not isinstance(raw, dict):
        return None
    video_id = positive_id(raw.get("id"))
    title = clean(raw.get("title"))
    return {
        "id": video_id,
        "title": title,
        "description": clean(raw.get("description")),
        "link": video_link(video_id, title) if video_id else None,
        "image": image(raw.get("imageId")),
        "stream_link": clean(raw.get("videoUrl")),
        "duration": clean(raw.get("durationStr")),
        "published_at": iso_time(raw.get("timestamp")),
        "language": clean(raw.get("language")),
        "type": clean(raw.get("videoType")),
        "source": clean(raw.get("source")),
        "is_premium": bool(raw.get("entitlements")),
        "tags": [{"name": clean(t.get("itemName")), "type": clean(t.get("itemType")), "id": to_int(t.get("itemId"))}
                 for t in raw.get("tags") or [] if isinstance(t, dict)],
    }


# ---- auction ----------------------------------------------------------------------------------------------------------

def auction_player(raw):
    if not isinstance(raw, dict):
        return None
    return {
        "id": to_int(raw.get("id")),
        "player": player_stub(raw.get("playerId"), raw.get("playerName"), raw.get("playerImageId")),
        "country": {"id": positive_id(raw.get("countryId")), "name": clean(raw.get("country"))},
        "role": clean(raw.get("role")),
        "base_price": clean(raw.get("basePrice")),
        "auction_price": clean(raw.get("auctionPrice")),
        "status": clean(raw.get("auctionStatus")),
        "team": team_stub(raw.get("playsFor"), None, raw.get("playsForTeam"), raw.get("teamImageId")),
        "is_capped": (clean(raw.get("cappedStatus")) or "").upper() == "CAPPED" if clean(raw.get("cappedStatus")) else None,
        "is_overseas": to_bool(raw.get("isPlayerOverseas")),
        "total_earnings": clean(raw.get("totalEarnings")),
        "intro": [clean(i) for i in raw.get("playerIntro") or [] if clean(i)],
        "season": clean(raw.get("season")),
        "updated_at": iso_time(raw.get("updatedTime")),
    }


# ---- HTML-only pages ------------------------------------------------------------------------------------------------

def soup(html):
    return BeautifulSoup(html or "", "html.parser")


def _main(doc):
    return doc.find("main") or doc


def _text(el):
    return clean(el.get_text(" ", strip=True)) if el is not None else None


def grouped_links(html, prefix, *, name_selector=None, extra=None):
    """Pages that render `<group header>` + `<a href=/prefix/…>` lists (team
    index, team roster, trending players) -> [{group, items}]. The header is
    the nearest preceding uppercase block (`bg-cbGrpHdrBkg`)."""
    doc = soup(html)
    groups = []
    current = None
    for el in _main(doc).find_all(["a", "div"]):
        if el.name == "div":
            classes = el.get("class") or []
            if "bg-cbGrpHdrBkg" in classes:
                current = {"group": _text(el), "items": []}
                groups.append(current)
            continue
        href = el.get("href") or ""
        if not href.startswith(prefix):
            continue
        entity_id = id_from_path(href)
        if not entity_id:
            continue
        img = el.find("img")
        name_el = el.select_one(name_selector) if name_selector else None
        item = {"id": entity_id, "name": _text(name_el) or _text(el), "link": absolute(href),
                "image": clean(img.get("src")) if img is not None else None}
        if extra:
            item.update(extra(el))
        if current is None:
            current = {"group": None, "items": []}
            groups.append(current)
        if not any(i["id"] == entity_id for i in current["items"]):
            current["items"].append(item)
    return groups


def series_list(html):
    """/cricket-schedule/series/<type>: name + date range per series link."""
    doc = soup(html)
    out = []
    seen = set()
    for a in _main(doc).find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/cricket-series/"):
            continue
        series_id = id_from_path(href)
        if not series_id or series_id in seen:
            continue
        divs = a.find_all("div")
        texts = [t for t in (_text(d) for d in divs) if t]
        name = texts[1] if len(texts) > 1 and texts[0] == " ".join(texts[1:]) else (texts[0] if texts else _text(a))
        dates = texts[-1] if len(texts) > 1 else None
        if dates and name and dates in name:
            name = clean(name.replace(dates, ""))
        seen.add(series_id)
        out.append({"id": series_id, "name": name, "link": series_link(series_id, name), "date_range": dates})
    return out


def news_cards(html):
    """News index / category pages: one card per story link."""
    doc = soup(html)
    out = []
    seen = set()
    for a in _main(doc).find_all("a", href=True):
        href = a["href"]
        if not re.match(r"^/cricket-news/\d+/", href):
            continue
        news_id = id_from_path(href)
        if news_id in seen:
            continue
        card = a
        for _ in range(4):
            if card.parent is None:
                break
            card = card.parent
            if card.name == "div" and card.find("img") is not None and card.find("p") is not None:
                break
        headline = _text(a) or clean(a.get("title"))
        if not headline:
            title_link = card.find("a", href=href, string=True)
            headline = _text(title_link) or clean(a.get("title"))
        img = card.find("img")
        intro = _text(card.find("p"))
        context_el = card.find("span", class_=lambda c: c and "uppercase" in c)
        context = None
        category = None
        if context_el is not None:
            parts = [clean(p) for p in (_text(context_el) or "").split("•")]
            parts = [p for p in parts if p]
            if parts:
                category = parts[0]
                context = parts[-1] if len(parts) > 1 else None
        seen.add(news_id)
        out.append({"id": news_id, "headline": headline, "intro": intro, "context": context, "category": category,
                    "link": absolute(href), "image": clean(img.get("src")).split("?")[0] if img is not None and img.get("src") else None})
    return out


def news_article(html, news_id):
    """The story page: headline, author, body paragraphs, tags, JSON-LD dates."""
    doc = soup(html)
    main = _main(doc)
    ld = {}
    for script in doc.find_all("script", type="application/ld+json"):
        try:
            import json as _json
            data = _json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "NewsArticle":
            ld = data
            break
    h1 = main.find("h1")
    headline = _text(h1) or clean(ld.get("headline"))
    author_link = main.find("a", href=lambda h: h and h.startswith("/cricket-news/author/"))
    author = None
    if author_link is not None:
        author = {"id": id_from_path(author_link["href"]), "name": _text(author_link), "link": absolute(author_link["href"])}
    context = None
    if h1 is not None:
        prev = h1.find_previous("span")
        context = _text(prev) if prev is not None and (prev.get("class") and "uppercase" in " ".join(prev.get("class"))) else None
    paragraphs = []
    body_root = h1.parent if h1 is not None else main
    while body_root is not None and not body_root.find_all("p"):
        body_root = body_root.parent
    for p in (body_root or main).find_all("p"):
        text = _text(p)
        if text and text not in paragraphs and not p.find_parent("a"):
            paragraphs.append(text)
    tags = []
    tags_header = main.find(lambda tag: tag.name in ("h3", "strong", "div") and _text(tag) == "TAGS")
    if tags_header is not None:
        for a in tags_header.parent.find_all("a", href=True):
            href = a["href"]
            kind = "team" if "/cricket-team/" in href else "player" if "/profiles/" in href else "series" if "/cricket-series/" in href else "topic"
            tags.append({"name": _text(a), "type": kind, "id": id_from_path(href), "link": absolute(href)})
    cover = None
    img = main.find("img", src=lambda s: s and "static.cricbuzz.com" in s)
    if img is not None:
        caption_el = img.find_next("span")
        cover = {"image": clean(img.get("src")).split("?")[0], "caption": _text(caption_el),
                 "credit": None}
        credit_el = caption_el.find_next("span") if caption_el is not None else None
        if credit_el is not None and (_text(credit_el) or "").startswith("©"):
            cover["credit"] = clean(_text(credit_el).lstrip("©"))
        if cover["caption"] and "©" in cover["caption"]:
            caption, _, credit = cover["caption"].partition("©")
            cover["caption"] = clean(caption)
            cover["credit"] = cover["credit"] or clean(credit)
    images = ld.get("image") if isinstance(ld.get("image"), list) else []
    return {
        "id": news_id,
        "headline": headline,
        "context": context or clean(ld.get("abstract")),
        "intro": clean(ld.get("backstory")),
        "link": clean(ld.get("url")) or news_link(news_id, headline),
        "author": author,
        "published_at": clean(ld.get("datePublished")),
        "modified_at": clean(ld.get("dateModified")),
        "is_free": to_bool(ld.get("isAccessibleForFree")),
        "cover_image": cover or ({"image": clean(images[0].get("url")), "caption": clean(images[0].get("name")), "credit": None} if images and isinstance(images[0], dict) else None),
        "body": paragraphs,
        "text": "\n\n".join(paragraphs) if paragraphs else clean(ld.get("articleBody")),
        "tags": tags,
    }


def gallery_photos(html, gallery_id):
    doc = soup(html)
    main = _main(doc)
    h1 = main.find("h1")
    photos = []
    for img in main.find_all("img", src=lambda s: s and "static.cricbuzz.com" in s and "/i1/c" in s):
        src = clean(img.get("src")).split("?")[0]
        if any(p["image"] == src for p in photos):
            continue
        caption = None
        block = img.parent
        for _ in range(3):
            if block is None:
                break
            cap = block.find(["p", "span", "div"], string=True)
            text = _text(cap) if cap is not None else None
            if text and text != _text(h1):
                caption = text
                break
            block = block.parent
        photos.append({"image": src, "caption": caption})
    tags = []
    tags_header = main.find(lambda tag: tag.name in ("h3", "strong", "div") and _text(tag) == "TAGS")
    if tags_header is not None:
        for a in tags_header.parent.find_all("a", href=True):
            href = a["href"]
            kind = "team" if "/cricket-team/" in href else "player" if "/profiles/" in href else "series" if "/cricket-series/" in href else "topic"
            tags.append({"name": _text(a), "type": kind, "id": id_from_path(href), "link": absolute(href)})
    headline = _text(h1)
    for heading in main.find_all(["h1", "h2"]):
        text = _text(heading)
        if text and text.lower() == (headline or "").lower() and text != text.lower():
            headline = text
            break
    return {"id": gallery_id, "headline": headline, "link": gallery_link(gallery_id, headline),
            "photo_count": len(photos), "photos": photos, "tags": tags}


def news_topics(html):
    doc = soup(html)
    out = []
    seen = set()
    for a in _main(doc).find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/cricket-news/info/"):
            continue
        topic_id = id_from_path(href)
        if not topic_id or topic_id in seen:
            continue
        seen.add(topic_id)
        parts = [t for t in (_text(x) for x in a.find_all(["span", "div", "h2", "h3"])) if t]
        name = parts[0] if parts else _text(a)
        description = parts[-1] if len(parts) > 1 and parts[-1] != name else None
        img = a.find("img")
        out.append({"id": topic_id, "name": name, "description": description, "link": absolute(href),
                    "image": clean(img.get("src")).split("?")[0] if img is not None and img.get("src") else None})
    return out


def html_table(html, *, first_table=True):
    """The player all-matches page: a <table> with a header row and series
    label rows -> [{series, ...cells}]."""
    doc = soup(html)
    table = _main(doc).find("table")
    if table is None:
        return []
    headers = None
    series = None
    out = []
    for tr in table.find_all("tr"):
        cells = [_text(c) for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        if headers is None and tr.find("th") is not None:
            headers = [header_key(c) for c in cells]
            continue
        if headers is None:
            headers = [header_key(c) for c in cells]
            continue
        if len(cells) == 1:
            series = cells[0]
            continue
        link = tr.find("a", href=True)
        record = {"series": series}
        for key, value in zip(headers, cells):
            record[key] = (parse_date_text(value) or clean(value)) if key == "date" else _cell(value)
        if link is not None:
            record["match_id"] = id_from_path(link["href"])
            record["match_link"] = absolute(link["href"])
        out.append(record)
    return out
