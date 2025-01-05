from pathlib import Path

from shared.processing_paths import ProcessingPaths, paths_from_unprocessed_path


def test_filenames() -> None:
    work_paths = paths_from_unprocessed_path(
        "some/path/to/my/unprocessed.mp3", "fix buzz!! bang? a show?? about stuff."
    )
    assert work_paths == ProcessingPaths(
        post_processed_audio_path=Path(
            "srv/fix buzz bang a show about stuff/unprocessed.mp3"
        ),
        audio_processing_dir=Path(
            "processing/fix buzz bang a show about stuff/unprocessed.mp3"
        ),
        classification_dir=Path(
            "processing/fix buzz bang a show about stuff/unprocessed.mp3/classification"
        ),
    )
