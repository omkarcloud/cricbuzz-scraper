"""Marshmallow request schemas for every /cricbuzz/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Cricbuzz resolvers and the per-route schemas. Every schema's
load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair): `match` / `series` / `team` / `player` / `venue` / `news`
/ `gallery` / `video` / `topic` / `author` each accept a bare Cricbuzz id
OR a pasted cricbuzz.com link (refs.py).
"""
from marshmallow import fields, validate

from schema_fields import (BaseSchema, ChoiceField, DateField, Flag, PageField, PositiveInt,
                           QueryField, RefField, StrippedString)
from cricbuzz import refs


# ---- id-or-link fields -------------------------------------------------------------------

class MatchRefField(RefField):
    resolver = staticmethod(refs.resolve_match)


class SeriesRefField(RefField):
    resolver = staticmethod(refs.resolve_series)


class TeamRefField(RefField):
    resolver = staticmethod(refs.resolve_team)


class PlayerRefField(RefField):
    resolver = staticmethod(refs.resolve_player)


class VenueRefField(RefField):
    resolver = staticmethod(refs.resolve_venue)


class NewsRefField(RefField):
    resolver = staticmethod(refs.resolve_news)


class GalleryRefField(RefField):
    resolver = staticmethod(refs.resolve_gallery)


class VideoRefField(RefField):
    resolver = staticmethod(refs.resolve_video)


class TopicRefField(RefField):
    resolver = staticmethod(refs.resolve_topic)


class AuthorRefField(RefField):
    resolver = staticmethod(refs.resolve_author)


def _innings():
    return PositiveInt(max_value=4, metadata={"description": "innings number 1-4"})


def _before():
    return StrippedString(required=False, load_default=None, validate=validate.Length(max=40),
                          metadata={"description": "the previous page's next_before"})


def _before_id():
    return PositiveInt(metadata={"description": "the previous page's next_before (a story id)"})


def _stats_type():
    return ChoiceField(list(refs.STATS_TYPES), load_default="most-runs")


def _format(default=None):
    return ChoiceField(refs.RANKING_FORMATS, load_default=default)


def _skill_type():
    return ChoiceField(["batting", "bowling"], load_default="batting")


class EmptySchema(BaseSchema):
    pass


# ---- matches ----------------------------------------------------------------------------------

class MatchListSchema(BaseSchema):
    type = ChoiceField(refs.MATCH_TYPES, load_default="all")


class ScheduleSchema(BaseSchema):
    type = ChoiceField(refs.SCHEDULE_TYPES, load_default="international")
    date = DateField()


class MatchSchema(BaseSchema):
    match = MatchRefField()


class MatchInningsSchema(MatchSchema):
    innings = _innings()


class MatchCommentarySchema(MatchSchema):
    innings = _innings()
    before = _before()


class MatchPlayerSchema(MatchSchema):
    player = PlayerRefField()
    type = _skill_type()


# ---- series -------------------------------------------------------------------------------------

class SeriesListSchema(BaseSchema):
    type = ChoiceField(refs.SERIES_TYPES, load_default="all")


class ArchiveSchema(BaseSchema):
    year = PositiveInt(max_value=2100)


class SeriesSchema(BaseSchema):
    series = SeriesRefField()


class SeriesSquadSchema(SeriesSchema):
    squad = fields.Integer(required=True, strict=False, validate=validate.Range(min=1),
                           metadata={"description": "a squad_id from /series/squads"})


class SeriesStatsSchema(SeriesSchema):
    stats_type = _stats_type()
    format = _format()
    team = StrippedString(required=False, load_default=None, validate=validate.Length(max=12),
                          metadata={"description": "a team id, or all"})


class SeriesNewsSchema(SeriesSchema):
    before = _before_id()


# ---- teams ---------------------------------------------------------------------------------------

class TeamListSchema(BaseSchema):
    type = ChoiceField(refs.TEAM_TYPES, load_default="international")


class TeamSchema(BaseSchema):
    team = TeamRefField()


class TeamStatsSchema(TeamSchema):
    stats_type = _stats_type()
    format = _format("test")
    year = StrippedString(required=False, load_default=None, validate=validate.Regexp(r"^(all|\d{4})$", error="Must be a year or all."))
    opponent = StrippedString(required=False, load_default=None, validate=validate.Length(max=12),
                              metadata={"description": "an opponent team id, or all"})


class TeamNewsSchema(TeamSchema):
    before = _before_id()


class TeamPhotosSchema(TeamSchema):
    before = PositiveInt(metadata={"description": "the previous page's next_before (an epoch in ms)"})


# ---- players ----------------------------------------------------------------------------------------

class PlayerSearchSchema(BaseSchema):
    query = QueryField(max_length=80, validate=validate.Length(min=2, max=80))


class PlayerSchema(BaseSchema):
    player = PlayerRefField()


class PlayerTypeSchema(PlayerSchema):
    type = _skill_type()


class PlayerNewsSchema(PlayerSchema):
    before = _before_id()


# ---- stats / venues ---------------------------------------------------------------------------------

class RankingsSchema(BaseSchema):
    category = ChoiceField(list(refs.RANKING_CATEGORIES), load_default="batting")
    gender = ChoiceField(refs.GENDERS, load_default="men")
    format = _format()


class StandingsSchema(BaseSchema):
    format = ChoiceField(["test", "odi"], load_default="test")
    season = PositiveInt(metadata={"description": "a season id from the response's seasons list"})


class RecordsSchema(BaseSchema):
    stats_type = _stats_type()
    format = _format("test")
    year = StrippedString(required=False, load_default=None, validate=validate.Regexp(r"^(all|\d{4})$", error="Must be a year or all."))
    team = StrippedString(required=False, load_default=None, validate=validate.Length(max=12))
    opponent = StrippedString(required=False, load_default=None, validate=validate.Length(max=12))


class VenueSchema(BaseSchema):
    venue = VenueRefField()


# ---- content ------------------------------------------------------------------------------------------

class NewsListSchema(BaseSchema):
    category = ChoiceField(list(refs.NEWS_CATEGORIES), load_default="latest")
    before = _before_id()


class NewsSchema(BaseSchema):
    news = NewsRefField()


class TopicSchema(BaseSchema):
    topic = TopicRefField()
    before = _before_id()


class AuthorSchema(BaseSchema):
    author = AuthorRefField()


class PhotosSchema(BaseSchema):
    before = PositiveInt(metadata={"description": "the previous page's next_before (an epoch in ms)"})


class GallerySchema(BaseSchema):
    gallery = GalleryRefField()


class VideosSchema(BaseSchema):
    collection = PositiveInt(metadata={"description": "a collection id from the video home"})
    before = PositiveInt(metadata={"description": "the previous page's next_before"})


class VideoSchema(BaseSchema):
    video = VideoRefField()


class AuctionPlayersSchema(BaseSchema):
    tournament = ChoiceField(["ipl", "wpl", "hunm", "hunw"], load_default="ipl")
    year = PositiveInt(max_value=2100)
    status = ChoiceField(refs.AUCTION_STATUSES, load_default="completed")
    page = PageField(max_page=50)
    currency = ChoiceField(refs.AUCTION_CURRENCIES, load_default="inr")
    sort = ChoiceField(list(refs.AUCTION_SORTS), load_default="recent")
    country = PositiveInt(metadata={"description": "a country (team) id, e.g. 2 for India"})
    role = StrippedString(required=False, load_default=None, validate=validate.Length(max=30))
    capped = Flag()
    team = PositiveInt(metadata={"description": "a franchise team id"})


class AuctionSearchSchema(BaseSchema):
    query = QueryField(max_length=80, validate=validate.Length(min=2, max=80))
    tournament = ChoiceField(["ipl", "wpl", "hunm", "hunw"], load_default="ipl")
    year = PositiveInt(max_value=2100)
