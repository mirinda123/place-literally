"""Rule-level checks for coarse recall and bidirectional language voting."""

from backend.similar import LanguageMeaning, _best_pair, _pair_score


def terms(en, fr):
    return {"en": LanguageMeaning(frozenset(en.split())),
            "fr": LanguageMeaning(frozenset(fr.split()))}


def test_short_meaning_recovers_reverse_only_relationship():
    short = terms("white peak", "pic blanc")
    long = terms("white peak river valley forest", "pic blanc fleuve vallée forêt")
    assert _pair_score(short, long) == _pair_score(long, short) == 2


def test_coarse_shared_words_are_not_enough_for_fine_match():
    left = terms("white peak", "pic blanc")
    right = terms("white river", "fleuve blanc")
    assert all(left[lang].terms & right[lang].terms for lang in left)
    assert _pair_score(left, right) == _pair_score(right, left) == 0


def test_opposite_directions_cannot_pool_language_votes():
    left = terms("white peak", "pic blanc fleuve vallée forêt")
    right = terms("white peak river valley forest", "pic blanc")
    # English only supports left→right; French only supports right→left.
    # Two languages share words, but neither direction earns two fine-filter votes.
    assert _pair_score(left, right) == _pair_score(right, left) == 0


def test_distinct_meanings_cannot_pool_language_votes():
    source = terms("white peak", "pic blanc")
    candidates = [terms("white peak", "port violet"), terms("violet harbor", "pic blanc")]
    assert _best_pair([source], candidates, "a", "b") is None


def test_tied_multisense_matches_choose_same_pair_when_reversed():
    white = terms("white peak", "pic blanc")
    violet = terms("violet harbor", "port violet")
    source, candidate = [white, violet], [violet, white]
    forward = _best_pair(source, candidate, "a", "b")
    reverse = _best_pair(candidate, source, "b", "a")
    assert forward[0] == reverse[0] == 2
    assert forward[2:] == (0, 1)
    assert reverse[2:] == (1, 0)


def test_empty_terms_require_equal_original_phrases_in_two_languages():
    source = {"en": LanguageMeaning(frozenset(), "in the city"),
              "fr": LanguageMeaning(frozenset(), "dans la ville")}
    different = {"en": LanguageMeaning(frozenset(), "in the country"),
                 "fr": LanguageMeaning(frozenset(), "dans le pays")}
    assert _pair_score(source, source) == 2
    assert _pair_score(source, different) == _pair_score(different, source) == 0
    assert _pair_score(source, {"en": source["en"]}) == 0
    assert _pair_score({"en": LanguageMeaning(frozenset())},
                       {"en": LanguageMeaning(frozenset())}) == 0


def test_weak_phrase_cannot_match_a_long_meaning_by_generic_words():
    weak = {"en": LanguageMeaning(frozenset(), "in the city"),
            "fr": LanguageMeaning(frozenset(), "dans la ville")}
    content = terms("shelter marsh", "abri marais")
    assert _pair_score(weak, content) == _pair_score(content, weak) == 0


def test_phrase_and_content_support_can_combine_without_pooling_directions():
    source = {"en": LanguageMeaning(frozenset(), "in the city"),
              "fr": LanguageMeaning(frozenset({"pic", "blanc"}))}
    candidate = {"en": source["en"],
                 "fr": LanguageMeaning(frozenset({"pic", "blanc", "fleuve", "vallée", "forêt"}))}
    assert _pair_score(source, candidate) == _pair_score(candidate, source) == 2
