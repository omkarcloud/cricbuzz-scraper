"""Offline tests for the Cricbuzz parsers — no network.

Every fixture in cricbuzz/fixtures/ is a real upstream payload captured on
2026-09-18: the /api route-handler JSON verbatim (lists trimmed), the data
objects lifted out of the pages' RSC payloads, and the <main> element of
the HTML-only pages. The assertions pin the field mapping that was decoded
from live data, so a silent upstream rename shows up here rather than as
nulls in a customer's response.

    python -m pytest cricbuzz/test_parsers.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cricbuzz import parsers as P  # noqa: E402
from cricbuzz import refs          # noqa: E402
from cricbuzz.rsc import deref, find_first, page_rows, parse_flight, undefined_to_none  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle) if name.endswith(".json") else handle.read()


# ---- refs ----------------------------------------------------------------------

def test_refs_accept_ids_and_links():
    assert refs.resolve_match("152742") == 152742
    assert refs.resolve_match(152742) == 152742
    assert refs.resolve_match("https://www.cricbuzz.com/live-cricket-scorecard/152742/zim-vs-aus") == 152742
    assert refs.resolve_team("https://www.cricbuzz.com/cricket-team/india/2/players") == 2
    assert refs.resolve_author("www.cricbuzz.com/cricket-news/author/vijay-tagore/67") == 67


def test_refs_reject_foreign_links_and_slugs():
    for bad in ("abc", "https://espncricinfo.com/match/1", "https://www.cricbuzz.com/cricket-series/ipl-2026/auction", 0):
        try:
            refs.resolve_match(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


# ---- rsc -----------------------------------------------------------------------

def test_flight_parser_honours_t_row_byte_lengths():
    # "é" is two UTF-8 bytes; the T length counts bytes, and the next row
    # starts right after them with no newline in between.
    text = '1:T3,é!2:{"a":1}\n3:["$","div",null,{"x":2}]\n'
    rows = parse_flight(text)
    assert rows["1"] == "é!"
    assert rows["2"] == {"a": 1}
    assert rows["3"][3] == {"x": 2}


def test_page_rows_and_deref_on_a_real_page():
    rows = page_rows(load("venue_page_flight.html"))
    block = find_first(rows, "venueDetails")
    assert block["venueDetails"]["ground"] == "Harare Sports Club"
    assert deref(rows, "$undefined") is None


def test_undefined_placeholders_become_none():
    assert undefined_to_none({"a": "$undefined", "b": ["$undefined", 1]}) == {"a": None, "b": [None, 1]}


# ---- scalars -------------------------------------------------------------------

def test_scalar_helpers():
    assert P.to_int("1,234") == 1234 and P.to_int("--") is None and P.to_int(True) == 1
    assert P.to_float("4.7") == 4.7 and P.to_number("53") == 53 and P.to_number("53.79") == 53.79
    assert P.iso_time(1789716600000) == "2026-09-18T07:30:00Z"
    assert P.iso_time("1789716600") == "2026-09-18T07:30:00Z"
    assert P.parse_date_text("November 05, 1988 (37 years)") == "1988-11-05"
    assert P.parse_date_text("19 Jul 26") == "2026-07-19"
    assert P.strip_html("<b>FOUR</b><br>next") == "FOUR\nnext"
    assert P.render_formats("B0$ up, B1$", {"bold": {"formatId": ["B0$", "B1$"], "formatValue": ["350", "x"]}}) == "350 up, x"
    assert P.status_category("In Progress") == "live" and P.status_category("Preview") == "upcoming"
    assert P.status_category("Complete") == "completed" and P.status_category("Abandon") == "completed"
    assert P.image(616517) == "https://static.cricbuzz.com/a/img/v1/i1/c616517/i.jpg?p=det&d=high"
    assert P.image(0) is None


# ---- match lists ---------------------------------------------------------------

def test_home_row_is_unwrapped_and_summarised():
    row = P.match_summary(load("home.json")["matches"][0])
    assert row["id"] == 152742 and row["format"] == "ODI" and row["status_category"] == "live"
    assert row["team1"]["short_name"] == "AUS" and row["team1"]["innings"][0]["runs"] == 356
    assert row["venue"]["name"] == "Harare Sports Club"
    assert row["series"]["id"] == 11997 and row["series"]["start_date"] == "2026-09-14"
    assert row["link"].startswith("https://www.cricbuzz.com/live-cricket-scores/152742/")


def test_recent_list_groups_by_type_then_series():
    groups = P.type_matches({"typeMatches": load("recent_list.json")["matches"]})
    assert groups[0]["type"] == "International"
    series = groups[0]["series"][0]
    assert series["id"] and series["match_count"] == len(series["matches"])
    assert all(m["status_category"] == "completed" for m in series["matches"])


def test_schedule_days():
    days = P.schedule_days(load("schedule.json"))
    assert days[0]["date"] == "2026-09-18" and days[0]["match_count"] >= 1
    match = days[0]["matches"][0]
    assert match["series"]["category"] == "International" and match["team1"]["flag"]


def test_dated_matches():
    days = P.dated_matches(load("series_matches.json")["matchDetails"])
    assert days[0]["date"] == "2026-09-15" and days[0]["matches"][0]["id"] == 152731


# ---- match detail --------------------------------------------------------------

def test_match_header_result_and_awards():
    header = P.match_header(load("miniscore_completed.json")["matchHeader"])
    assert header["result"] == {"type": "win", "winning_team_id": 2, "winning_team": "India", "margin": 127,
                                "is_by_runs": True, "is_by_innings": False}
    assert header["players_of_the_match"][0]["name"] == "Abhishek Sharma"
    assert header["toss"]["decision"] == "Bowling" and header["is_complete"] is True
    assert header["innings_order"][0]["batting_team"] == "IND"


def test_match_info_carries_officials_and_series_results():
    info = P.match_info(load("match_info.json")["matchInfo"])
    assert [u["name"] for u in info["umpires"]] == ["Iknow Chabi", "Rashid Riaz"]
    assert info["third_umpire"]["name"] == "Alex Wharf" and info["referee"]["country"] == "ZIM"
    assert info["series"]["results"] == {"test": "Series levelled 0-0"}
    assert info["venue"]["coordinates"]["latitude"] == -17.814114


def test_miniscore():
    live = P.miniscore(load("livescore.json")["miniscore"])
    assert live["batting_team"]["runs"] == 136 and live["target"] == 357
    assert live["striker"]["name"] == "Brendan Taylor" and live["bowler"]["economy"] == 3.8
    assert live["innings"][0]["batting_team"] == "ZIM" and live["innings"][0]["balls"]
    assert live["powerplays"][0]["type"] == "Mandatory" and live["recent_performance"][0]["label"] == "Last 10 overs"


def test_scorecard():
    card = P.scorecard(load("scorecard.json"))
    innings = card["innings"][0]
    assert innings["batting_team"]["short_name"] == "AUS" and innings["score"]["runs"] == 356
    assert innings["extras"]["wides"] == 8
    marsh = innings["batting"][0]
    assert marsh["player"]["id"] == 6250 and marsh["is_captain"] is True and marsh["runs"] == 53
    assert marsh["dismissal"] == {"text": "b Wellington Masakadza", "type": "BOWLED", "bowler_id": 8460, "fielder_ids": []}
    assert innings["bowling"][0]["player"]["name"] == "Blessing Muzarabani" and innings["bowling"][0]["economy"] == 7.6
    assert innings["fall_of_wickets"][0] == {"wicket_number": 1, "player": P.player_stub(6250, "Mitchell Marsh"), "score": 130, "over": 18.6, "ball": 114}
    assert innings["partnerships"][0]["runs"] == 130 and innings["partnerships"][0]["batter2"]["name"] == "Travis Head"
    assert innings["powerplays"][0]["runs"] == 78


def test_commentary_feed_is_newest_first_with_over_summary():
    feed = P.commentary_feed(load("commentary.json")["matchCommentary"])
    assert feed[0]["time"] >= feed[-1]["time"]
    assert all(e["events"] == [] or "all" not in e["events"] for e in feed)
    breaks = [e for e in feed if e.get("over_summary")]
    assert breaks and breaks[0]["over_summary"]["batting_team"]["score"]


def test_highlights_render_placeholders_and_events():
    entries = P.commentary_list(load("highlights.json")["commentaryList"])
    assert entries[0]["text"].startswith("Brad Evans to Oliver Peake, SIX")
    assert entries[0]["events"] == ["team-hundred", "six"] and entries[0]["runs"] == 6
    assert entries[0]["batter"]["strike_rate"] == 235.29


def test_over_summary_ball_and_partnerships():
    over = P.over_summary(load("overs.json")["paginatedData"][0])
    assert over["over"] == 50 and over["balls"] == "2 6 2 Wd 6 6 1" and over["bowler"]["wickets"] == 3
    balls = P.balls_map(load("balls_map.json"))
    assert balls["score"]["runs"] == 356 and balls["balls"][1]["events"] == ["team-hundred", "six"]
    assert balls["batters"][0]["strike_rate"] == 84.13
    innings = P.partnership_graph(load("partnerships.json"))
    assert innings[0]["batting_team"]["short_name"] == "AUS" and innings[0]["partnerships"][0]["batter1"]["image"]


def test_match_squads_groups():
    squads = P.match_squads(load("match_squads.json"))
    zim = squads["team1"]
    assert zim["short_name"] == "ZIM" and zim["flag"]
    assert zim["playing_xi"][0]["name"] == "Brian Bennett" and zim["bench"][0]["is_substitute"] is True
    assert zim["support_staff"][0]["role"] == "Head Coach"


def test_match_graphs():
    graphs = P.match_graphs(load("match_graphs.json"))
    assert graphs["team1"]["short_name"] == "ZIM" and graphs["team1"]["color"] == "#DF9916"
    assert graphs["runs"][0]["over"] == 0 and "1" in graphs["win_probability"]
    assert graphs["innings"][0]["label"] == "ZIM (2nd Inn)"


def test_player_performance():
    perf = P.player_performance(load("player_performance.json"))
    assert perf["player"]["name"] == "Mitchell Marsh" and perf["batting_summary"] == "53(63)"
    innings = perf["batting"]["innings"][0]
    assert innings["summary"]["runs"] == "53(63)" and innings["dismissed_by_id"] == 8460
    assert innings["matchups"][0]["bowler"]["name"] == "Newman Nyamhuri" and innings["matchups"][0]["balls"] == 11
    assert perf["batting"]["series_stats"]["stats"][0] == {"stat": "Matches", "value": 1, "rank": None}


# ---- series / teams / tables ---------------------------------------------------

def test_series_squads_and_players():
    groups = P.series_squads(load("series_squads.json"))
    assert groups[0]["format"] == "ODI" and groups[0]["squads"][0]["squad_id"] == 128680
    players = P.series_squad_players(load("series_squad_players.json"))
    assert players[0]["group"] == "BATTERS" and players[0]["players"][0]["name"] == "Travis Head"


def test_points_table():
    table = P.points_table(load("points_table.json"))
    assert table["format"] == "T20" and table["legend"]["NRR"] == "Net Run Rate"
    team = table["groups"][0]["teams"][0]
    assert team["team"]["short_name"] == "RCB" and team["net_run_rate"] == 0.783 and team["qualify_status"] == "Q"
    assert team["matches"][0]["is_win"] is True and team["matches"][0]["net_run_rate_change"] == 2.907


def test_icc_standings():
    standings = P.icc_standings(load("icc_standings.json"), "test")
    assert standings["seasons"][0]["is_active"] is True
    assert standings["teams"][0]["team"]["name"] == "Australia" and standings["teams"][0]["percentage"] == 80.0


def test_records_table_lifts_the_player_id():
    table = P.stats_table(load("records.json"))
    assert table["headers"][:3] == ["PLAYER", "MATCHES", "INNS"]
    assert table["rows"][0]["player"] == P.player_stub(25, "Sachin Tendulkar")
    assert table["rows"][0]["runs"] == 15921 and table["rows"][0]["strike_rate"] == 54.08
    assert table["filters"]["formats"][1] == {"id": "2", "name": "odi"}


def test_stats_types_public_names():
    types = P.stats_types({"Batting": [{"value": "mostRuns", "header": "Most Runs", "category": "Batting"}]})
    assert types == [{"stats_type": "most-runs", "name": "Most Runs", "category": "Batting"}]


def test_rankings_rows():
    data = load("rankings.json")["formatTypesData"]
    row = P.ranking_row(undefined_to_none(data["odi"]["rank"][0]))
    assert row["rank"] == 1 and row["name"] == "Shubman Gill" and row["country"] == "India" and row["image"]


def test_archive_years():
    years = P.archive_years(load("archive.json"))
    assert years[0]["year"] == "2026" and years[0]["series"][0]["start_date"] == "2026-09-18"
    assert years[0]["series"][0]["image"] is None       # isDefaultImage -> no image


# ---- players -------------------------------------------------------------------

def test_player_profile():
    data = load("player_profile.json")
    profile = P.player_profile(data, data["bio_text"])
    assert profile["name"] == "Virat Kohli" and profile["date_of_birth"] == "1988-11-05" and profile["age"] == 37
    assert profile["batting_stats"]["odi"]["runs"] == 14941 and profile["batting_stats"]["test"]["hundreds"] == 30
    assert profile["bowling_stats"]["test"]["economy"] == 2.88
    assert profile["rankings"]["batting"]["odi"] == {"current": 3, "best": 1}
    assert profile["career"][0]["format"] == "t20" and profile["career"][0]["debut"]["match_id"] == 2300
    assert profile["recent_batting"][0]["match_id"] == 129480 and profile["recent_batting"][0]["date"] == "2026-07-19"
    assert profile["bio"].startswith("A spunky") and profile["teams"][0]["name"] == "India"
    assert profile["news"][0]["headline"]


def test_player_form_and_search():
    form = P.player_form(load("player_form.json"))
    assert form["innings"][0]["match_id"] == 75623 and form["innings"][0]["series"]["name"] == "ICC Cricket World Cup 2023"
    assert form["innings"][0]["wickets"] == "1-13" and form["filters"][0]["key"] == "matchType"
    players = [P.search_player(p) for p in load("player_search.json")["player"]]
    assert players[0]["id"] == 1413 and players[0]["date_of_birth"] == "1988-11-05"


# ---- venue ---------------------------------------------------------------------

def test_venue_details():
    venue = P.venue_details(load("venue.json"), 69)
    assert venue["capacity"] == 10000 and venue["ends"] == ["City End", "Club House End"]
    assert venue["stats"]["test"]["matches"] == 41 and venue["stats"]["test"]["average_scores"]["first_innings"] == 318
    assert venue["stats"]["test"]["highest_totals"][0]["team"]["short_name"] == "RSA"


# ---- content -------------------------------------------------------------------

def test_story_shapes():
    story = P.story(load("story_list.json")["storyList"][0])
    assert story["id"] == 140184 and story["published_at"] == "2026-09-15T15:46:21Z" and story["cover_image"]["credit"] == "Getty"
    paged = P.story(load("news_pagination.json")["paginatedData"][0])
    assert paged["published_ago"] == "6h ago" and paged["published_at"] is None and paged["image"]


def test_gallery_video_auction():
    galleries = [P.gallery_summary(g) for g in load("gallery_list.json")]
    assert galleries[0]["id"] == 6070 and galleries[0]["published_at"] == "2026-06-29T17:55:29Z"
    collections = P.video_collections(load("videos.json"))
    assert collections[0]["name"] == "Latest Videos" and collections[0]["videos"][0]["duration"] == "5:27"
    video = P.video_details(load("video.json"))
    assert video["id"] == 209730 and video["stream_link"].startswith("https://cdnapisec.kaltura.com/") and video["tags"][0]["type"] == "series"
    player = P.auction_player(load("auction_players.json")["auctionPlayersList"][0])
    assert player["player"]["name"] == "Sam Curran" and player["is_capped"] is True and player["team"]["short_name"] == "RR"


# ---- HTML-only pages -----------------------------------------------------------

def test_news_cards_and_article():
    cards = P.news_cards(load("news_index.html"))
    assert cards[0]["id"] == 140216 and cards[0]["context"] == "Agarkar future" and cards[0]["category"] == "News"
    article = P.news_article(load("news_article.html"), 140216)
    assert article["author"] == {"id": 67, "name": "Vijay Tagore", "link": "https://www.cricbuzz.com/cricket-news/author/vijay-tagore/67"}
    assert article["published_at"] == "2026-09-18T09:41:16.000Z" and len(article["body"]) >= 10
    assert article["cover_image"]["credit"] == "AFP" and "©" not in article["cover_image"]["caption"]
    assert [t["type"] for t in article["tags"]] == ["team", "player", "player"]


def test_grouped_link_pages():
    teams = P.grouped_links(load("teams_index.html"), "/cricket-team/")
    assert teams[0]["group"] == "Test Teams" and teams[0]["items"][0] == {
        "id": 2, "name": "India", "link": "https://www.cricbuzz.com/cricket-team/india/2",
        "image": "https://static.cricbuzz.com/a/img/v1/72x54/i1/c776162/india.jpg"}
    roster = P.grouped_links(load("team_players.html"), "/profiles/")
    assert [g["group"] for g in roster] == ["BATSMEN", "ALL ROUNDER", "WICKET KEEPER", "BOWLER"]
    trending = P.grouped_links(load("trending_players.html"), "/profiles/", name_selector="span.text-base")
    assert trending[0]["items"][0]["name"] == "Shadab Khan"


def test_series_list_topics_gallery_and_table():
    series = P.series_list(load("series_list.html"))
    assert series[0]["id"] == 7572 and series[0]["date_range"] == "Feb 15 - Dec 29"
    topics = P.news_topics(load("news_topics.html"))
    assert topics[0] == {"id": 375, "name": "Auction", "description": "Stories from the Cricket auctions around the world",
                         "link": "https://www.cricbuzz.com/cricket-news/info/375/auction", "image": None}
    gallery = P.gallery_photos(load("gallery.html"), 6070)
    assert gallery["photo_count"] == 11 and gallery["photos"][0]["caption"].startswith("On a Perth pitch")
    assert gallery["headline"] == "The defining moments of Ben Stokes' international career"
    innings = P.html_table(load("player_all_matches.html"))
    assert innings[0] == {"series": "India tour of England, 2026", "score": "74(60)", "opponent": "ENG", "format": "ODI",
                          "venue": "London", "date": "2026-07-19", "strike_rate": 123.3, "fours": 4, "sixes": 3}
