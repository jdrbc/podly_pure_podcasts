import tempfile

from podcast_processor.audio import clip_segments_with_fade, get_audio_duration_ms

TEST_FILE_DURATION = 66_048
TEST_FILE_PATH = "src/tests/data/count_0_99.mp3"


def test_get_duration_ms() -> None:
    assert get_audio_duration_ms(TEST_FILE_PATH) == TEST_FILE_DURATION


def test_clip_segment_with_fade() -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(2_000, 3_000)],
            100,
            TEST_FILE_PATH,
            temp_file.name,
        )

        print(f"clipped file written to {temp_file.name}")

        assert get_audio_duration_ms(temp_file.name) == TEST_FILE_DURATION - 1_000 + 256
