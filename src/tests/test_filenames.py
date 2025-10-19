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
