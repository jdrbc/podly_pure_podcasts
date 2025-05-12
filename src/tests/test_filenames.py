from pathlib import Path

from shared.processing_paths import ProcessingPaths, paths_from_unprocessed_path


def test_filenames() -> None:
    """Test filename processing with sanitized characters."""
    work_paths = paths_from_unprocessed_path(
        "some/path/to/my/unprocessed.mp3", "fix buzz!! bang? a show?? about stuff."
    )
    # Expect sanitized directory name with special characters removed and spaces replaced with underscores
    assert work_paths == ProcessingPaths(
        post_processed_audio_path=Path(
            "srv/fix_buzz_bang_a_show_about_stuff/unprocessed.mp3"
        )
    )
