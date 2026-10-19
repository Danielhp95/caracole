import pytest

from caracole.config import RankPolicy
from caracole.rank import Candidate, bayes, prior_mean, rank_by_rating, rank_guitar, rank_sheets

P = RankPolicy()


def c(tab_id, rating, votes, *, version=1, coverage=None, label=None, kind="chords"):
    return Candidate(provider="ug", tab_id=str(tab_id), kind=kind, rating=rating, votes=votes,
                     version=version, label=label, coverage=coverage)


def test_bayes_formula():
    assert bayes(4.85, 81, 4.8, 10) == pytest.approx((81 * 4.85 + 10 * 4.8) / 91)
    assert bayes(5.0, 0, 4.2, 10) == pytest.approx(4.2)


def test_prior_is_vote_weighted():
    cands = [c(1, 4.0, 10), c(2, 5.0, 30), c(3, 1.0, 0)]
    assert prior_mean(cands) == pytest.approx((40 + 150) / 40)
    assert prior_mean([c(1, 4.0, 0)]) == 0.0


def test_few_votes_shrink_toward_the_prior():
    # C is the song's vote-weighted mean (about 4.63 here), so a lone 5-star vote
    # shrinks to about 4.66 and loses to 4.8 from 270 votes.
    ranked = rank_by_rating([c(1, 5.0, 1), c(2, 4.8, 270), c(3, 4.4, 200)], P)
    assert [x.tab_id for x in ranked] == ["2", "1", "3"]


def test_complete_beats_higher_rated_partial():
    ranked = rank_sheets([c(1, 4.9, 300, coverage=0.5), c(2, 4.2, 20, coverage=0.95)], P)
    assert [x.tab_id for x in ranked] == ["2", "1"]


def test_among_complete_the_higher_score_wins():
    ranked = rank_sheets([c(1, 4.2, 20, coverage=0.9), c(2, 4.8, 200, coverage=0.85)], P)
    assert [x.tab_id for x in ranked] == ["2", "1"]


def test_partial_kept_when_nothing_complete():
    ranked = rank_sheets([c(1, 4.0, 5, coverage=0.3), c(2, 4.5, 50, coverage=0.6)], P)
    assert [x.tab_id for x in ranked] == ["2", "1"]


def test_unknown_coverage_counts_as_incomplete():
    ranked = rank_sheets([c(1, 4.9, 500, coverage=None), c(2, 3.0, 2, coverage=0.81)], P)
    assert [x.tab_id for x in ranked] == ["2", "1"]


def test_guitar_penalty_and_variant_bonus():
    gp = [
        c(1, 4.9, 100, label="solo", kind="guitar-pro"),
        c(2, 4.6, 100, kind="guitar-pro"),
        c(3, 4.5, 100, label="acoustic", kind="guitar-pro"),
    ]
    assert [x.tab_id for x in rank_guitar(gp, P)] == ["2", "3", "1"]
    assert [x.tab_id for x in rank_guitar(gp, P, variant="acoustic")] == ["3", "2", "1"]
    unplugged = [c(4, 4.5, 100, label="unplugged", kind="guitar-pro"), c(5, 4.6, 100, kind="guitar-pro")]
    assert rank_guitar(unplugged, P, variant="acoustic")[0].tab_id == "4"


def test_ties_break_on_version_then_id():
    ranked = rank_guitar([c(9, 0, 0, version=2, kind="tabs"), c(10, 0, 0, version=1, kind="tabs"),
                          c(8, 0, 0, version=1, kind="tabs")], P)
    assert [x.tab_id for x in ranked] == ["8", "10", "9"]


def test_scores_are_set_on_candidates():
    cands = [c(1, 4.0, 10), c(2, 5.0, 30)]
    rank_by_rating(cands, P)
    assert all(x.score > 0 for x in cands)
