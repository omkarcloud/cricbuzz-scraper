"""Cricbuzz reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair). Every entity ref accepts a bare numeric Cricbuzz id OR a pasted
cricbuzz.com link (the slug in a link is decorative; only the id matters):

  match    152742  | https://www.cricbuzz.com/live-cricket-scores/152742/zim-vs-aus-2nd-odi
                   | …/live-cricket-scorecard/152742/… | …/cricket-match-facts/152742/…
                   | …/cricket-match-squads/152742/…  | …/player-match-performance/match/152742/player/6250/batting
  series   11997   | https://www.cricbuzz.com/cricket-series/11997/australia-tour-of-zimbabwe-2026[/matches]
  team     2       | https://www.cricbuzz.com/cricket-team/india/2[/players]
  player   1413    | https://www.cricbuzz.com/profiles/1413/virat-kohli
  venue    69      | https://www.cricbuzz.com/cricket-venues/69/harare-sports-club
  news     140216  | https://www.cricbuzz.com/cricket-news/140216/bcci-office-bearers-…
  gallery  6070    | https://www.cricbuzz.com/cricket-gallery/6070/the-defining-moments-…
  video    209864  | https://www.cricbuzz.com/cricket-videos/209864/vaibhav-has-to-wait-…
  topic    375     | https://www.cricbuzz.com/cricket-news/info/375/auction
  author   67      | https://www.cricbuzz.com/cricket-news/author/vijay-tagore/67

Every Cricbuzz link is `/<section>/<id>/<slug>` except the team page
(`/cricket-team/<slug>/<id>`) and the author page, so "the first all-digit
path segment" is the id in every case — with the one exception of
`/cricket-series/ipl-2026/auction/...`, which carries no numeric id and is
rejected with a message.

Also holds the tables the routes share: list categories, format ids, the
records catalogue, news categories and ranking categories (all read off
the live site 2026-09-18).
"""
import re
from urllib.parse import urlparse

_DIGITS_RE = re.compile(r"^\d{1,9}$")
_HOST_RE = re.compile(r"(^|\.)cricbuzz\.com$")


def _id_from(value, kind):
    """A bare id or a cricbuzz.com link -> int id."""
    if isinstance(value, int) and not isinstance(value, bool):
        if value <= 0:
            raise ValueError(f"{kind} id must be positive")
        return value
    text = str(value or "").strip()
    if _DIGITS_RE.match(text):
        return int(text)
    if text.startswith(("http://", "https://", "//", "www.")):
        url = text if "://" in text else "https:" + text if text.startswith("//") else "https://" + text
        parsed = urlparse(url)
        if not _HOST_RE.search((parsed.hostname or "").lower()):
            raise ValueError(f"{kind} must be a numeric Cricbuzz id or a cricbuzz.com link")
        for segment in parsed.path.split("/"):
            if _DIGITS_RE.match(segment):
                return int(segment)
        raise ValueError(f"no numeric {kind} id in link {text!r}")
    raise ValueError(f"{kind} must be a numeric Cricbuzz id or a cricbuzz.com link, got {text!r}")


def resolve_match(value):
    return _id_from(value, "match")


def resolve_series(value):
    return _id_from(value, "series")


def resolve_team(value):
    return _id_from(value, "team")


def resolve_player(value):
    return _id_from(value, "player")


def resolve_venue(value):
    return _id_from(value, "venue")


def resolve_news(value):
    return _id_from(value, "news")


def resolve_gallery(value):
    return _id_from(value, "gallery")


def resolve_video(value):
    return _id_from(value, "video")


def resolve_topic(value):
    return _id_from(value, "topic")


def resolve_author(value):
    return _id_from(value, "author")


# ---- list categories ---------------------------------------------------------------
# The live/recent/upcoming lists and the schedule are grouped by matchType;
# `type` filters those groups. Team and series lists are separate pages per
# category (international = the index page).
MATCH_TYPES = ["all", "international", "league", "domestic", "women"]
SCHEDULE_TYPES = ["all", "international", "league", "domestic", "women"]
TEAM_TYPES = ["international", "domestic", "league", "women"]
SERIES_TYPES = ["all", "international", "league", "domestic", "women"]

# ---- formats -------------------------------------------------------------------------
# The records/points-table handlers take the numeric match type; rankings
# take the word.
FORMAT_IDS = {"test": "1", "odi": "2", "t20": "3"}
FORMAT_NAMES = {"1": "test", "2": "odi", "3": "t20"}

# ---- records catalogue --------------------------------------------------------------
# statsType tokens of /api/cricket-stats/stats-table, the same list the
# series and team stats tabs use. Exposed as kebab-case publicly.
STATS_TYPES = {
    "most-runs": "mostRuns",
    "highest-score": "highestScore",
    "best-batting-average": "highestAvg",
    "best-batting-strike-rate": "highestSr",
    "most-hundreds": "mostHundreds",
    "most-fifties": "mostFifties",
    "most-fours": "mostFours",
    "most-sixes": "mostSixes",
    "most-nineties": "mostNineties",
    "most-wickets": "mostWickets",
    "best-bowling-average": "lowestAvg",
    "best-bowling-innings": "bestBowlingInnings",
    "most-five-wickets": "mostFiveWickets",
    "best-economy": "lowestEcon",
    "best-bowling-strike-rate": "lowestSr",
}
STATS_TYPE_LABELS = {
    "mostRuns": "Most Runs", "highestScore": "Highest Scores",
    "highestAvg": "Best Batting Average", "highestSr": "Best Batting Strike Rate",
    "mostHundreds": "Most Hundreds", "mostFifties": "Most Fifties",
    "mostFours": "Most Fours", "mostSixes": "Most Sixes", "mostNineties": "Most Nineties",
    "mostWickets": "Most Wickets", "lowestAvg": "Best Bowling Average",
    "bestBowlingInnings": "Best Bowling", "mostFiveWickets": "Most 5 Wickets Haul",
    "lowestEcon": "Best Economy", "lowestSr": "Best Bowling Strike Rate",
}
BATTING_STATS = {"mostRuns", "highestScore", "highestAvg", "highestSr", "mostHundreds",
                 "mostFifties", "mostFours", "mostSixes", "mostNineties"}
_STATS_PUBLIC = {v: k for k, v in STATS_TYPES.items()}


def stats_type_public(token):
    return _STATS_PUBLIC.get(token, token)


# ---- rankings ------------------------------------------------------------------------
RANKING_CATEGORIES = {"batting": "batting", "bowling": "bowling",
                      "all-rounder": "all-rounder", "teams": "teams"}
GENDERS = ["men", "women"]
RANKING_FORMATS = ["test", "odi", "t20"]

# ---- news ----------------------------------------------------------------------------
# Category -> page path. The /api/cricket-news/{lastId}/{n} pagination
# handler ignores its category segment (verified 2026-09-18: every n returns
# the latest list), so categories are read from their pages.
NEWS_CATEGORIES = {
    "latest": "/cricket-news/latest-news",
    "premium": "/cricket-news/editorial/cb-plus",
    "spotlight": "/cricket-news/editorial/spotlight",
    "opinions": "/cricket-news/editorial/editorial-list",
    "specials": "/cricket-news/editorial/specials",
    "stats": "/cricket-news/editorial/stats-analysis",
    "interviews": "/cricket-news/editorial/interviews",
    "live-blogs": "/cricket-news/editorial/live-blogs",
}

# ---- match squads ----------------------------------------------------------------------
SQUAD_GROUPS = {"playing XI": "playing_xi", "bench": "bench", "support staff": "support_staff"}

# ---- auction ---------------------------------------------------------------------------
AUCTION_STATUSES = ["completed", "upcoming"]
AUCTION_SORTS = {
    "recent": ("apl.updated_at", "DESC"),
    "featured": ("apl.is_editor_pick", "DESC"),
    "base-price-desc": ("apl.base_price", "DESC"),
    "base-price-asc": ("apl.base_price", "ASC"),
    "auction-price-desc": ("apl.auction_price", "DESC"),
    "auction-price-asc": ("apl.auction_price", "ASC"),
}
AUCTION_CURRENCIES = ["inr", "usd"]
