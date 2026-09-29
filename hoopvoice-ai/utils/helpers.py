import re


def strip_ssml(text: str) -> str:
    """Remove all XML/SSML tags and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def calculate_audio_duration(ssml_text: str) -> float:
    """Strip SSML tags, count words, use formula duration = word_count / 2.5 + 0.3"""
    clean_text = strip_ssml(ssml_text)
    word_count = len(clean_text.split())
    return (word_count / 2.5) + 0.3


def test_duration_calculation():
    """Test function for `calculate_audio_duration`"""
    sample_ssml = "<speak><emphasis level='strong'>OH WOW!</emphasis> <break time='200ms'/> What a shot.</speak>"
    duration = calculate_audio_duration(sample_ssml)
    # Expected words: "OH WOW! What a shot." = 5 words
    # 5 / 2.5 = 2.0 + 0.3 = 2.3 seconds
    assert abs(duration - 2.3) < 0.1, f"Expected ~2.3 seconds, got {duration}"
    return True
