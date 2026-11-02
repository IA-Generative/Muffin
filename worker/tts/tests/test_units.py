import numpy as np
import pytest

from app.audio import encode
from app.config import load_settings
from app.voices import NON_ENGLISH_LANGUAGES, is_english_voice, resolve_voice

# The 115 voices of the model at the pinned revision (voices/voices.json).
REAL_VOICES = (
    "AirportAnnouncer Alfred Arabic ArabicFalconer ArabicMother ArabicNews AudiobookNarratorFemale Bella "
    "BoredTeenager Bruno CalmHostageNegotiator Chinese ChineseLivestreamSeller ChineseNewsCctv "
    "ChineseXianxiaMaster Claire Dante Diana Dolores DutchBaker DutchGrandpaStory DutchWeatherPresenter "
    "Edith Eleanor Elliot FairytaleNarratorWhimsical Frank French FrenchDocumentary "
    "FrenchGrandmereRecette FrenchTeacher FrenchWaiter German GermanKneipe GermanProfessor "
    "GermanTrainAnnouncement Grace GrandmaBedtimeStory GriefEulogy Herbert Hindi HindiBollywoodDrama "
    "HindiCollegeFriends HindiDadiKahani HindiYogaTeacher Hugo IndonesianNewsAnchor IndonesianTourGuide "
    "Iris Italian ItalianFashionDesigner ItalianFootballFan ItalianGondolier ItalianNonnaKitchen "
    "ItalianOperaTenor JapaneseAnimeHeroine JapaneseGrandma JapaneseSalarymanApology "
    "JapaneseTrainConductor Jasper Julian Kiki KoreanGrandpaAdvice KoreanKdramaConfession "
    "KoreanNewsAnchor Laurence Leo Luna Maeve Marcus Martha Matthew Miles NervousFirstDate "
    "NewsAnchorFemale Otis PilotCabinAnnouncement PolishBabciaPierogi PolishMountainGuide "
    "PolishNewsAnchor PolishPoetryStudent Portuguese PortugueseBeach PortugueseBusiness PortugueseFado "
    "PortugueseGrandpaFarm PortugueseNewsAnchor Raven Reginald Rosie Russian RussianBabushka "
    "RussianFairyTale RussianHockeyCheer RussianLiteratureTeacher RussianSpaceControl RussianTaxiDriver "
    "Sable Saoirse SarcasticCoworker Serena Spanish SpanishAbuela SpanishBreakupSad SpanishNews "
    "SpanishTango TurkishFisherman TurkishGrandmaCooking TurkishNewsAnchor Victor Victoria Vincent "
    "Walter WeatherPresenterCheerful Willow"
).split()


@pytest.mark.parametrize(
    "name", ["French", "FrenchTeacher", "SpanishAbuela", "Arabic", "PortugueseFado", "KoreanNewsAnchor"]
)
def test_language_voices_are_not_english(name: str):
    assert not is_english_voice(name)


@pytest.mark.parametrize("name", ["Bella", "Bruno", "AirportAnnouncer", "SarcasticCoworker", "Dante", "Iris", "Hugo"])
def test_other_voices_are_english(name: str):
    assert is_english_voice(name)


def test_every_language_word_is_covered():
    assert len(NON_ENGLISH_LANGUAGES) == 15
    assert all(not is_english_voice(f"{language}Something") for language in NON_ENGLISH_LANGUAGES)
    assert len(REAL_VOICES) == 115
    assert sum(not is_english_voice(v) for v in REAL_VOICES) == 65


def test_resolve_voice():
    available = ["French", "Bella"]
    assert resolve_voice(None, available, "French") == "French"
    assert resolve_voice("  ", available, "French") == "French"
    assert resolve_voice("bella", available, "French") == "Bella"
    assert resolve_voice("alloy", available, "French") is None


def test_settings_defaults_and_overrides():
    settings = load_settings({})
    assert (settings.max_chars, settings.max_concurrency, settings.request_timeout_seconds) == (4000, 1, 120.0)
    assert (settings.default_voice, settings.weights, settings.api_key) == ("French", "packed", None)
    custom = load_settings({"TTS_API_KEY": "k", "TTS_MAX_CHARS": "50", "TTS_WEIGHTS": "emb4", "TTS_TORCH_THREADS": "3"})
    assert (custom.api_key, custom.max_chars, custom.weights, custom.torch_threads) == ("k", 50, "emb4", 3)
    assert load_settings({"TTS_API_KEY": "  "}).api_key is None


@pytest.mark.parametrize(
    "env",
    [
        {"TTS_WEIGHTS": "fp8"},
        {"TTS_MAX_CHARS": "0"},
        {"TTS_MAX_CONCURRENCY": "many"},
        {"TTS_REQUEST_TIMEOUT_SECONDS": "-1"},
    ],
)
def test_bad_settings_fail_at_startup(env: dict[str, str]):
    with pytest.raises(ValueError):
        load_settings(env)


def test_clipping_does_not_wrap_around():
    samples = np.frombuffer(encode(np.array([2.0, -2.0, 0.0], dtype=np.float32), 24000, "pcm"), dtype="<i2")
    assert samples.tolist() == [32767, -32767, 0]
