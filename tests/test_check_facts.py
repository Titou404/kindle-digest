"""Tests for the free fidelity check of the summaries (eval/check_facts.py)."""

from check_facts import check, interpretations, numbers_in, seen_text


def test_a_number_can_be_read_the_english_or_the_french_way():
    assert interpretations("1,200") == {1200.0, 1.2}
    assert interpretations("3,2") == {3.2}
    assert interpretations("2 300") == {2300.0}
    assert interpretations("1,200.5") == {1200.5}
    assert interpretations("2026") == {2026.0}


def test_numbers_match_across_languages_and_number_words():
    source = "Inflation rose to 3.2 per cent in October, and three people were hurt."
    flags = check("L'inflation a atteint 3,2 % en octobre ; 3 blessés.", source)
    assert flags["numbers"] == 2 and flags["unsupported_numbers"] == []
    assert 3.0 in numbers_in(source)  # "three"


def test_scales_rounding_and_versions_are_not_false_alarms():
    source = "Speed: ~10.7k tokens/s, 170k lines, 93.4% saved, a $1.5bn deal, version 0.4.0."
    written = ("10 700 tokens par seconde, 170 000 lignes, 93 % économisés, "
               "un contrat de 1,5 milliard, version 0.4.0.")
    assert check(written, source)["unsupported_numbers"] == []
    # Truncating is not rounding: 93.9% is 94 %, not 93 %.
    assert check("93 % économisés", "93.9% saved")["unsupported_numbers"]


def test_an_invented_number_is_flagged_with_its_context():
    flags = check("Le plan coûtera 45 milliards d'euros.", "The plan will cost 40bn euros.")
    [flag] = flags["unsupported_numbers"]
    assert flag["value"] == "45 milliards" and "coûtera" in flag["context"]


def test_quotes_are_checked_in_french_and_counted_as_translated_in_english():
    fr_source = "Le ministre a déclaré que « la France ne va pas être la Grèce » devant les députés."
    assert check("Il affirme : « La France ne va pas être la Grèce ».", fr_source)["unsupported_quotes"] == []
    assert check("Il affirme : « La France va sortir de l'euro ».", fr_source)["unsupported_quotes"]
    en_source = "The minister said that the country would never default on its debt."
    assert check("Il affirme : « jamais de défaut ».", en_source)["translated_quotes"] == 1


def test_false_friend_billion_is_flagged():
    assert check("Un contrat de 2 billions de dollars.", "a $2bn contract")["false_friends"] == ["billions"]


def test_the_model_is_checked_against_the_text_it_was_given():
    assert len(seen_text("mot " * 3000, 6000)) <= 6001
    assert seen_text("court", 6000) == "court"
