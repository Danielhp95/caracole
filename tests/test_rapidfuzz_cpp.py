"""helpers/rapidfuzz_cpp.py, the transcription of rapidfuzz-cpp 3.3.4 the Kotlin port copies, against the installed
rapidfuzz 3.14.5 (its compiled scorers, never ``fuzz_py``) on seeded random pairs."""

import random

import pytest
from rapidfuzz import fuzz, process

from helpers import rapidfuzz_cpp as cpp


def aligned(a, b):
    r = fuzz.partial_ratio_alignment(a, b)
    return [r.score, r.src_start, r.src_end, r.dest_start, r.dest_end]


def test_the_installed_rapidfuzz_is_the_one_transcribed():
    import rapidfuzz

    assert rapidfuzz.__version__ == "3.14.5"
    assert fuzz.partial_ratio_alignment.__module__.startswith("rapidfuzz.fuzz_cpp")


def test_the_bit_parallel_lcs_is_the_dynamic_programmes():
    rng = random.Random(1)
    for name, a, b in cpp.random_pairs(rng, 300) + cpp.random_pairs(rng, 60, long=True):
        assert cpp.lcs_bits(a, b) == cpp.lcs(a, b) == cpp.lcs_bits(b, a), (name, a, b)


def test_the_alignment_is_rapidfuzzs_on_the_nine_letters_it_was_first_checked_on():
    rng = random.Random(11)
    for _ in range(1000):
        k = rng.randint(1, 90)
        a = "".join(rng.choice("abcde fgh") for _ in range(k))
        b = "".join(rng.choice("abcde fgh") for _ in range(k + rng.randint(0, 50)))
        assert cpp.alignment(a, b) == aligned(a, b), (a, b)


@pytest.mark.parametrize("long", [False, True], ids=["short", "long"])
def test_every_scorer_is_rapidfuzzs_on_every_alphabet(long):
    rng = random.Random(7 if long else 5)
    for name, a, b in cpp.random_pairs(rng, 400 if long else 2000, long=long):
        assert cpp.alignment(a, b) == aligned(a, b), (name, a, b)
        assert cpp.alignment(b, a) == aligned(b, a), (name, b, a)
        assert cpp.ratio(a, b) == fuzz.ratio(a, b), (name, a, b)
        assert cpp.token_sort_ratio(a, b) == fuzz.token_sort_ratio(a, b), (name, a, b)


def test_the_search_tests_pair_aligns_where_cpp_puts_it():
    assert aligned("banma", "song dongye ban ma ban ma") == cpp.alignment("banma", "song dongye ban ma ban ma") \
        == [80.0, 0, 5, 19, 24]


def test_two_empty_strings_are_alike_and_one_is_nothing_like_another():
    for a, b in (("", ""), ("", "a"), ("ab", ""), ("", " ")):
        assert cpp.alignment(a, b) == aligned(a, b)
        assert cpp.ratio(a, b) == fuzz.ratio(a, b)
        assert cpp.token_sort_ratio(a, b) == fuzz.token_sort_ratio(a, b)
    assert fuzz.ratio("", "") == 100.0


def test_nbsp_splits_words_only_in_a_string_cpython_stores_wider_than_a_byte():
    assert fuzz.token_sort_ratio("b\xa0a", "a b") != 100.0
    assert fuzz.token_sort_ratio("b\xa0aĀ", "a bĀ") == cpp.token_sort_ratio("b\xa0aĀ", "a bĀ")
    assert cpp.sorted_split("b\xa0a") == "b\xa0a"
    assert cpp.sorted_split("b\xa0aĀ") == "aĀ b"
    assert cpp.sorted_split("b\x85a\U0001f600") == "a\U0001f600 b"


def test_extract_is_rapidfuzzs_ties_by_index_and_the_cutoff_kept():
    rng = random.Random(3)
    for _ in range(300):
        alphabet = cpp.ALPHABETS[rng.choice(sorted(cpp.ALPHABETS))]
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 9)))
        choices = [query[:rng.randint(0, len(query))] + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 3)))
                   for _ in range(rng.randint(0, 12))]
        choices += rng.sample(choices, min(len(choices), 3))  # ties
        for cutoff in (0, 75, 80, 90):
            for limit in (None, 1, 3, 20):
                got = process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=cutoff, limit=limit)
                assert [tuple(r) for r in got] == cpp.extract(query, choices, cutoff, limit), (query, choices)
