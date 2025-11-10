from shared.processing_paths import (
    ProcessingPaths,
    get_srv_root,
    paths_from_unprocessed_path,
)


def test_filenames() -> None:
    """Test filename processing with sanitized characters."""
    work_paths = paths_from_unprocessed_path(
        "some/path/to/my/unprocessed.mp3", "fix buzz!! bang? a show?? about stuff."
    )
    # Expect sanitized directory name with special characters removed and spaces replaced with underscores
    assert work_paths == ProcessingPaths(
        post_processed_audio_path=get_srv_root()
        / "fix_buzz_bang_a_show_about_stuff"
        / "unprocessed.mp3",
    )


def test_long_filenames() -> None:
    """Test that long filenames are truncated to prevent path too long errors."""
    # Test with a very long feed title
    long_title = "A" * 200  # 200 character title
    work_paths = paths_from_unprocessed_path(
        "some/path/to/my/unprocessed.mp3", long_title
    )
    # Should be truncated to 100 characters
    expected_title = "A" * 100
    assert work_paths == ProcessingPaths(
        post_processed_audio_path=get_srv_root()
        / expected_title
        / "unprocessed.mp3",
    )
