from datetime import datetime

from pydantic import BaseModel

from rsc.enums import RankedPlaylist, RewardLevel, RLStatType


class Rank(BaseModel):
    division: int
    mmr: int
    played: int
    playlist: RankedPlaylist
    rank: str
    streak: int


class Rewards(BaseModel):
    progress: int
    level: RewardLevel


class PlayerRanks(BaseModel):
    ranks: list[Rank]
    reward: Rewards


class Stat(BaseModel):
    value: int
    name: RLStatType


class Profile(BaseModel):
    presence: str
    name: str


class ClubMember(BaseModel):
    joined: datetime
    name: str


class ClubColors(BaseModel):
    primary: str
    accent: str


class Club(BaseModel):
    verified: bool
    created: datetime
    owner: str
    tag: str
    news: str
    name: str
    members: list[ClubMember]
    colors: ClubColors


class Title(BaseModel):
    color: str
    name: str


class PlaylistPopulation(BaseModel):
    population: int
    name: str


class Population(BaseModel):
    online: int
    playlists: list[PlaylistPopulation]


class NewsArticle(BaseModel):
    slug: str
    image: str
    title: str


class ArticleResult(BaseModel):
    articles: list[NewsArticle]


class Tournament(BaseModel):
    players: int
    starts: datetime
    mode: str


class TournamentResult(BaseModel):
    tournaments: list[Tournament]
