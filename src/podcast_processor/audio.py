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
