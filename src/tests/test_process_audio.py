import tempfile

from podcast_processor.audio import clip_segments_with_fade, get_audio_duration_ms

TEST_FILE_DURATION = 66_048
TEST_FILE_PATH = "src/tests/data/count_0_99.mp3"


def test_get_duration_ms() -> None:
    assert get_audio_duration_ms(TEST_FILE_PATH) == TEST_FILE_DURATION


def test_clip_segment_with_fade() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 3_000, 21_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        assert (
            get_audio_duration_ms(temp_file.name)
            == TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )


def test_clip_segment_with_fade_beginning() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 0, 18_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        assert (
            get_audio_duration_ms(temp_file.name)
            == TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )


def test_clip_segment_with_fade_end() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = (
        TEST_FILE_DURATION - 18_000,
        TEST_FILE_DURATION,
    )

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        assert (
            get_audio_duration_ms(temp_file.name)
            == TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )
