from pathlib import Path
from typing import List, Optional, Tuple

import ffmpeg  # type: ignore[import-untyped]


def get_audio_duration_ms(file_path: str) -> Optional[int]:
    try:
        probe = ffmpeg.probe(file_path)
        format_info = probe["format"]
        duration_seconds = float(format_info["duration"])
        duration_milliseconds = duration_seconds * 1000
        return int(duration_milliseconds)
    except ffmpeg.Error as e:
        print("An error occurred while trying to probe the file:")
        print(e.stderr.decode())
        return None


def clip_segments_with_fade(
    ad_segments_ms: List[Tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
) -> None:

    in_stream = ffmpeg.input(in_path)
    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None

    trimmed_list = []

    last_end = 0
    for start_ms, end_ms in ad_segments_ms:
        trimmed_list.extend(
            [
                in_stream.filter(
                    "atrim", start=last_end / 1000.0, end=start_ms / 1000.0
                ),
                in_stream.filter(
                    "atrim", start=start_ms / 1000.0, end=(start_ms + fade_ms) / 1000.0
                ).filter("afade", t="out", ss=0, d=fade_ms / 1000.0),
                in_stream.filter(
                    "atrim", start=(end_ms - fade_ms) / 1000.0, end=end_ms / 1000.0
                ).filter("afade", t="in", ss=0, d=fade_ms / 1000.0),
            ]
        )

        last_end = end_ms

    if last_end != audio_duration_ms:
        trimmed_list.append(
            in_stream.filter(
                "atrim", start=last_end / 1000.0, end=audio_duration_ms / 1000.0
            )
        )

    ffmpeg.concat(*trimmed_list, v=0, a=1).output(out_path).overwrite_output().run()


def trim_file(in_path: Path, out_path: Path, start_ms: int, end_ms: int) -> None:
    try:
        # First decode to PCM then encode to MP3 to avoid frame boundary issues
        (
            ffmpeg.input(str(in_path))
            .filter("aselect", f"between(t,{start_ms/1000},{end_ms/1000})")
            .filter("asetpts", "PTS-STARTPTS")
            .output(
                str(out_path), format="mp3", acodec="libmp3lame", ar=44100, ab="128k"
            )
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as e:
        print(f"Error trimming file from {start_ms}ms to {end_ms}ms:")
        if e.stderr:
            print(e.stderr.decode())
        raise


def split_audio(
    audio_file_path: Path,
    audio_chunk_path: Path,
    chunk_size_bytes: int,
) -> List[Tuple[Path, int]]:

    audio_chunk_path.mkdir(exist_ok=True)

    duration_ms = get_audio_duration_ms(str(audio_file_path))
    assert duration_ms is not None

    chunk_duration_ms = (
        chunk_size_bytes / audio_file_path.stat().st_size
    ) * duration_ms
    chunk_duration_ms = int(chunk_duration_ms)

    num_chunks = (duration_ms + chunk_duration_ms - 1) // chunk_duration_ms

    chunks: List[Tuple[Path, int]] = []

    for i in range(num_chunks):
        start_offset_ms = i * chunk_duration_ms
        end_offset_ms = min((i + 1) * chunk_duration_ms, duration_ms)

        export_path = audio_chunk_path / f"{i}.mp3"
        trim_file(audio_file_path, export_path, start_offset_ms, end_offset_ms)
        chunks.append((export_path, start_offset_ms))

    return chunks
