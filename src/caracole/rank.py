"""Ranking versions: lyric completeness first for sheets, then a Bayesian rating.

The rating is shrunk toward the song's own average by its vote count (plan §3):
``(v·R + m·C) / (v + m)`` with m = ``RankPolicy.prior_votes`` (10) and C the
vote-weighted mean of the song's versions. A 5.0 from one vote does not beat a
4.8 from 270 votes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from caracole.config import RankPolicy
from caracole.normalize import canonical_variant
from caracole.versions import complete

PARTIAL_LABELS = frozenset({"intro", "solo", "outro", "riff", "lesson"})


@dataclass
class Candidate:
    """One version competing for a slot."""

    provider: str
    tab_id: str
    kind: str
    rating: float
    votes: int
    version: int
    label: str | None = None
    coverage: float | None = None
    score: float = 0.0
    version_id: int | None = None


class Rated(Protocol):
    """Anything UG rates by votes: a ``Candidate``, or a tab an artist page lists (ug/artist_tabs.py)."""

    rating: float
    votes: int


def bayes(rating: float, votes: int, prior: float, m: int) -> float:
    return (votes * rating + m * prior) / (votes + m) if votes + m else 0.0


def prior_mean(cands: Sequence[Rated]) -> float:
    """The vote-weighted mean rating of a song's versions (0 when nobody voted)."""
    total = sum(c.votes for c in cands)
    return sum(c.votes * c.rating for c in cands) / total if total else 0.0


def _tiebreak(c: Candidate) -> tuple[int, int, str]:
    return (c.version, len(c.tab_id), c.tab_id)


def _score(cands: Sequence[Candidate], policy: RankPolicy, variant: str | None) -> None:
    prior = prior_mean(cands)
    want = canonical_variant(variant)
    for c in cands:
        s = bayes(c.rating, c.votes, prior, policy.prior_votes)
        if c.label in PARTIAL_LABELS:
            s -= policy.label_penalty
        if want and canonical_variant(c.label) == want:
            s += policy.variant_bonus
        c.score = s


def rank_by_rating(cands: Sequence[Candidate], policy: RankPolicy, *, variant: str | None = None) -> list[Candidate]:
    """By Bayesian score alone (used to pick which sheets are worth scoring for coverage)."""
    cands = list(cands)
    _score(cands, policy, variant)
    return sorted(cands, key=lambda c: (-c.score, *_tiebreak(c)))


def is_complete(c: Candidate, policy: RankPolicy) -> bool:
    return complete(c.coverage, policy.coverage_threshold)


def rank_sheets(cands: Sequence[Candidate], policy: RankPolicy, *, variant: str | None = None) -> list[Candidate]:
    """Complete sheets (coverage ≥ threshold) first, then by score; unknown coverage is incomplete.

    Partial labels (an "intro" chords version, say) are penalized too, which only
    matters when coverage can't separate the candidates.
    """
    cands = list(cands)
    _score(cands, policy, variant)
    return sorted(cands, key=lambda c: (not is_complete(c, policy), -c.score, *_tiebreak(c)))


# Guitar parts rank by score alone, with the penalty for intro/solo/outro/riff/lesson labels that every
# score carries.
rank_guitar = rank_by_rating
