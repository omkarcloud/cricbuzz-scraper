"""Cache TTL per /cricbuzz/* endpoint (cache.py, keyed on the validated
params — marshmallow fills the defaults, so `?type=all` and no `type` share
a row).

Tiers follow how fast Cricbuzz itself moves each surface: the live score
changes every ball (the site polls it every 3 s), a finished match never
changes again, and the catalogues (team lists, records) change a few
times a season. Routes that serve BOTH live and finished matches from one
path (every /matches/* detail tab) take the short tier — a stale live
score is the one error a cricket API cannot afford, and the upstream is
cheap.
"""
from datetime import timedelta

# --- live surfaces -----------------------------------------------------------
LIVE_SCORE_CACHE = timedelta(seconds=5)
LIVE_LIST_CACHE = timedelta(seconds=30)
COMMENTARY_CACHE = timedelta(seconds=20)

# --- match detail ------------------------------------------------------------
MATCH_DETAIL_CACHE = timedelta(minutes=1)        # details, scorecard, overs, highlights
MATCH_HEAVY_CACHE = timedelta(minutes=3)         # full commentary, ball map, graphs, player performance
MATCH_STATIC_CACHE = timedelta(hours=1)          # squads, match news

# --- lists / schedules -------------------------------------------------------
RECENT_LIST_CACHE = timedelta(minutes=5)
SCHEDULE_CACHE = timedelta(minutes=30)
SERIES_LIST_CACHE = timedelta(hours=6)
ARCHIVE_CACHE = timedelta(hours=12)

# --- series / teams ----------------------------------------------------------
SERIES_CACHE = timedelta(hours=1)                # details, matches, venues
SQUADS_CACHE = timedelta(hours=6)
POINTS_TABLE_CACHE = timedelta(minutes=30)
STATS_CACHE = timedelta(hours=6)                 # series/team/records tables
TEAM_CACHE = timedelta(hours=6)
ROSTER_CACHE = timedelta(hours=12)

# --- players -----------------------------------------------------------------
SEARCH_CACHE = timedelta(hours=12)
TRENDING_CACHE = timedelta(hours=1)
PLAYER_CACHE = timedelta(hours=6)

# --- rankings / standings / venues ------------------------------------------
RANKINGS_CACHE = timedelta(hours=12)             # ICC updates weekly
STANDINGS_CACHE = timedelta(hours=3)
RECORD_TYPES_CACHE = timedelta(days=7)
VENUE_CACHE = timedelta(days=1)

# --- content -----------------------------------------------------------------
NEWS_LIST_CACHE = timedelta(minutes=10)
ARTICLE_CACHE = timedelta(hours=6)
TOPICS_CACHE = timedelta(hours=12)
PHOTOS_CACHE = timedelta(hours=1)
GALLERY_CACHE = timedelta(days=1)
VIDEOS_CACHE = timedelta(minutes=30)
VIDEO_CACHE = timedelta(hours=6)
AUCTION_CACHE = timedelta(minutes=10)
AUCTION_SEASONS_CACHE = timedelta(days=1)
