import tempfile
from pathlib import Path

from podcast_processor.audio import (
    clip_segments_with_fade,
    get_audio_duration_ms,
    split_audio,
)

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


def test_split_audio() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        split_audio(Path(TEST_FILE_PATH), temp_dir_path, 38_000)

        expected = {
            "0.mp3": (6_384, 25_773),
            "1.mp3": (6_384, 25_773),
            "2.mp3": (6_384, 25_773),
            "3.mp3": (6_384, 25_773),
            "4.mp3": (6_384, 25_773),
            "5.mp3": (6_384, 25_773),
            "6.mp3": (6_384, 25_773),
            "7.mp3": (6_384, 25_773),
            "8.mp3": (6_384, 25_773),
            "9.mp3": (6_384, 25_773),
            "10.mp3": (2_784, 11_373),
        }

        for split in temp_dir_path.iterdir():
            assert split.name in expected
            duration_ms, filesize = expected[split.name]
            actual_duration = get_audio_duration_ms(str(split))
            assert (
                duration_ms == actual_duration
            ), f"unexpected filesize for {split}. found {actual_duration}, expected {duration_ms}"
            assert abs(filesize - split.stat().st_size) <= 10, f"filesize differs by more than 10 bytes for {split}. found {split.stat().st_size}, expected {filesize}"
