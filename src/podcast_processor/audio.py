import math
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

    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None

    trimmed_list = []

    last_end = 0
    for start_ms, end_ms in ad_segments_ms:
        trimmed_list.extend(
            [
                ffmpeg.input(in_path).filter(
                    "atrim", start=last_end / 1000.0, end=start_ms / 1000.0
                ),
                ffmpeg.input(in_path)
                .filter(
                    "atrim", start=start_ms / 1000.0, end=(start_ms + fade_ms) / 1000.0
                )
                .filter("afade", t="out", ss=0, d=fade_ms / 1000.0),
                ffmpeg.input(in_path)
                .filter("atrim", start=(end_ms - fade_ms) / 1000.0, end=end_ms / 1000.0)
                .filter("afade", t="in", ss=0, d=fade_ms / 1000.0),
            ]
        )

        last_end = end_ms

    if last_end != audio_duration_ms:
        trimmed_list.append(
            ffmpeg.input(in_path).filter(
                "atrim", start=last_end / 1000.0, end=audio_duration_ms / 1000.0
            )
        )

    ffmpeg.concat(*trimmed_list, v=0, a=1).output(out_path).overwrite_output().run()


def trim_file(in_path: Path, out_path: Path, start_ms: int, end_ms: int) -> None:
    duration_ms = end_ms - start_ms

    if duration_ms <= 0:
        return

    start_sec = max(start_ms, 0) / 1000.0
    duration_sec = duration_ms / 1000.0

    (
        ffmpeg.input(str(in_path))
        .output(
            str(out_path),
            ss=start_sec,
            t=duration_sec,
            acodec="copy",
            vn=None,
        )
        .overwrite_output()
        .run()
    )


def split_audio(
    audio_file_path: Path,
    audio_chunk_path: Path,
    chunk_size_bytes: int,
) -> List[Tuple[Path, int]]:

    audio_chunk_path.mkdir(parents=True, exist_ok=True)

    duration_ms = get_audio_duration_ms(str(audio_file_path))
    assert duration_ms is not None
    if chunk_size_bytes <= 0:
        raise ValueError("chunk_size_bytes must be a positive integer")

    file_size_bytes = audio_file_path.stat().st_size
    if file_size_bytes == 0:
        raise ValueError("Cannot split zero-byte audio file")

    chunk_ratio = chunk_size_bytes / file_size_bytes
    chunk_duration_ms = max(
        1, math.ceil(duration_ms * chunk_ratio)
    )

    num_chunks = max(1, math.ceil(duration_ms / chunk_duration_ms))

    chunks: List[Tuple[Path, int]] = []

    for i in range(num_chunks):
        start_offset_ms = i * chunk_duration_ms
        if start_offset_ms >= duration_ms:
            break

        end_offset_ms = min(duration_ms, (i + 1) * chunk_duration_ms)

        export_path = audio_chunk_path / f"{i}.mp3"
        trim_file(audio_file_path, export_path, start_offset_ms, end_offset_ms)
        chunks.append((export_path, start_offset_ms))

    return chunks
