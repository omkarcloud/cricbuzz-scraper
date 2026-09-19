"""The 58 Cricbuzz endpoints. Every path is served with and without the
`/cricbuzz` prefix, so code generated against the hosted API (paths like
/matches/live) runs unchanged against this server.

Params are validated by the same marshmallow schemas the hosted API uses
(cricbuzz/schemas.py), so defaults, enums and error messages are identical:
unknown params are rejected, ONE param per input accepts a bare Cricbuzz id
or a pasted cricbuzz.com link, and every failure maps to the same status
code you get from the hosted API.
"""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from cricbuzz import content, matches, players, schemas, series, stats, teams

PREFIX = "/cricbuzz"


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(path, schema, impl):
    """Validate the query with the endpoint's schema, run it, and map every
    failure the way the hosted API does: bad params -> 400, missing entity
    -> 404, upstream failure or block -> 502, anything else -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(impl(**data))
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"cricbuzz rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"cricbuzz blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"cricbuzz {path} failed: {e}"}, 502)
    except Exception as e:
        return json_response({"error": f"cricbuzz {path} failed: {type(e).__name__}: {e}"}, 500)


# (public path, request schema, endpoint function) — the order of the docs.
ENDPOINTS = [
    ("/matches/live", schemas.MatchListSchema, matches.get_live),
    ("/matches/details", schemas.MatchSchema, matches.get_details),
    ("/matches/scorecard", schemas.MatchSchema, matches.get_scorecard),
    ("/matches/live-score", schemas.MatchSchema, matches.get_live_score),
    ("/matches/commentary", schemas.MatchCommentarySchema, matches.get_commentary),
    ("/matches/full-commentary", schemas.MatchInningsSchema, matches.get_full_commentary),
    ("/matches/highlights", schemas.MatchInningsSchema, matches.get_highlights),
    ("/matches/overs", schemas.MatchCommentarySchema, matches.get_overs),
    ("/matches/ball-by-ball", schemas.MatchInningsSchema, matches.get_ball_by_ball),
    ("/matches/partnerships", schemas.MatchSchema, matches.get_partnerships),
    ("/matches/squads", schemas.MatchSchema, matches.get_squads),
    ("/matches/graphs", schemas.MatchSchema, matches.get_graphs),
    ("/matches/player-performance", schemas.MatchPlayerSchema, matches.get_player_performance),
    ("/matches/news", schemas.MatchSchema, matches.get_news),
    ("/matches/recent", schemas.MatchListSchema, matches.get_recent),
    ("/matches/upcoming", schemas.MatchListSchema, matches.get_upcoming),
    ("/matches/schedule", schemas.ScheduleSchema, matches.get_schedule),
    ("/series/details", schemas.SeriesSchema, series.get_details),
    ("/series/matches", schemas.SeriesSchema, series.get_matches),
    ("/series/points-table", schemas.SeriesSchema, series.get_points_table),
    ("/series/stats", schemas.SeriesStatsSchema, series.get_stats),
    ("/series/squads", schemas.SeriesSchema, series.get_squads),
    ("/series/squad-players", schemas.SeriesSquadSchema, series.get_squad_players),
    ("/series/venues", schemas.SeriesSchema, series.get_venues),
    ("/series/news", schemas.SeriesNewsSchema, series.get_news),
    ("/series", schemas.SeriesListSchema, series.get_list),
    ("/series/archive", schemas.ArchiveSchema, series.get_archive),
    ("/teams/details", schemas.TeamSchema, teams.get_details),
    ("/teams/players", schemas.TeamSchema, teams.get_players),
    ("/teams/schedule", schemas.TeamSchema, teams.get_schedule),
    ("/teams/results", schemas.TeamSchema, teams.get_results),
    ("/teams/stats", schemas.TeamStatsSchema, teams.get_stats),
    ("/teams/news", schemas.TeamNewsSchema, teams.get_news),
    ("/teams/photos", schemas.TeamPhotosSchema, teams.get_photos),
    ("/teams", schemas.TeamListSchema, teams.get_list),
    ("/players/search", schemas.PlayerSearchSchema, players.search),
    ("/players/details", schemas.PlayerSchema, players.get_details),
    ("/players/matches", schemas.PlayerTypeSchema, players.get_matches),
    ("/players/form", schemas.PlayerTypeSchema, players.get_form),
    ("/players/news", schemas.PlayerNewsSchema, players.get_news),
    ("/players/trending", schemas.EmptySchema, players.get_trending),
    ("/rankings", schemas.RankingsSchema, stats.get_rankings),
    ("/standings", schemas.StandingsSchema, stats.get_standings),
    ("/records", schemas.RecordsSchema, stats.get_records),
    ("/records/types", schemas.EmptySchema, stats.get_record_types),
    ("/venues/details", schemas.VenueSchema, stats.get_venue),
    ("/news", schemas.NewsListSchema, content.get_news),
    ("/news/article", schemas.NewsSchema, content.get_article),
    ("/news/topics", schemas.EmptySchema, content.get_topics),
    ("/news/topic", schemas.TopicSchema, content.get_topic_news),
    ("/news/author", schemas.AuthorSchema, content.get_author),
    ("/photos", schemas.PhotosSchema, content.get_photos),
    ("/photos/gallery", schemas.GallerySchema, content.get_gallery),
    ("/videos", schemas.VideosSchema, content.get_videos),
    ("/videos/details", schemas.VideoSchema, content.get_video),
    ("/auction/players", schemas.AuctionPlayersSchema, content.get_auction_players),
    ("/auction/search", schemas.AuctionSearchSchema, content.search_auction),
    ("/auction/seasons", schemas.EmptySchema, content.get_auction_seasons),
]


def mount(path, schema, impl):
    """Serve one endpoint at /path and /cricbuzz/path."""
    def handler():
        return call(path, schema, impl)
    handler.__name__ = "cricbuzz_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


for _path, _schema, _impl in ENDPOINTS:
    mount(_path, _schema, _impl)


@route("/", method="GET")
@route("/health", method="GET")
@route(PREFIX + "/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
