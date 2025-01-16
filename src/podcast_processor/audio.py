import gc
from typing import List, Optional, Tuple

import ffmpeg
from pydub import AudioSegment  # type: ignore[import-untyped]


def get_audio_duration_ms(file_path: str) -> Optional[int]:
    try:
        # Run ffmpeg.probe to get the file information
        probe = ffmpeg.probe(file_path)

        # Extract the duration from the probe data
        format_info = probe["format"]
        duration_seconds = float(format_info["duration"])  # Duration is in seconds

        # Convert duration from seconds to milliseconds
        duration_milliseconds = duration_seconds * 1000

        return int(duration_milliseconds)
    except ffmpeg.Error as e:
        print("An error occurred while trying to probe the file:")
        print(e.stderr.decode())
        return None


def get_ad_fade_out(
    audio: AudioSegment, ad_start_ms: int, fade_ms: int
) -> AudioSegment:
    fade_out = audio[ad_start_ms : ad_start_ms + fade_ms]
    assert isinstance(fade_out, AudioSegment)

    fade_out = fade_out.fade_out(fade_ms)
    return fade_out


def get_ad_fade_in(audio: AudioSegment, ad_end_ms: int, fade_ms: int) -> AudioSegment:
    fade_in = audio[ad_end_ms - fade_ms : ad_end_ms]
    assert isinstance(fade_in, AudioSegment)

    fade_in = fade_in.fade_in(fade_ms)
    return fade_in


def clip_segments_with_fade(
    ad_segments_ms: List[Tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
) -> None:
    audio = AudioSegment.from_file(in_path)

    new_audio = AudioSegment.empty()
    last_end = 0
    for start, end in ad_segments_ms:
        new_audio += audio[last_end:start]
        new_audio += get_ad_fade_out(audio, start, fade_ms)
        new_audio += get_ad_fade_in(audio, end, fade_ms)
        last_end = end
        gc.collect()
    if last_end != audio.duration_seconds * 1000:
        new_audio += audio[last_end:]
    new_audio.export(out_path, format="mp3")
