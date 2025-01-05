import gc
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, cast

from jinja2 import Template
from openai import APIError, OpenAI
from pydub import AudioSegment  # type: ignore[import-untyped]

from app import db, logger
from app.models import Post, Transcript
from podcast_processor.model_output import clean_and_parse_model_output
from shared.config import (
    Config,
    LocalWhisperConfig,
    RemoteWhisperConfig,
    TestWhisperConfig,
)
from shared.processing_paths import ProcessingPaths, paths_from_unprocessed_path

from .transcribe import (
    LocalWhisperTranscriber,
    RemoteWhisperTranscriber,
    Segment,
    TestWhisperTranscriber,
    Transcriber,
)


def get_post_processed_audio_path(post: Post) -> Optional[ProcessingPaths]:
    """
    Generate the processed audio path based on the post's unprocessed audio path.
    Returns None if unprocessed_audio_path is not set.
    """
    unprocessed_path = post.unprocessed_audio_path
    if not unprocessed_path or not isinstance(unprocessed_path, str):
        logger.warning(f"Post {post.id} has no unprocessed_audio_path.")
        return None

    title = post.feed.title
    if not title or not isinstance(title, str):
        logger.warning(f"Post {post.id} has no feed title.")
        return None

    return paths_from_unprocessed_path(unprocessed_path, title)


class PodcastProcessor:
    lock_lock = threading.Lock()
    locks: Dict[str, threading.Lock] = {}
    transcriber: Transcriber

    def __init__(
        self,
        config: Config,
    ) -> None:
        super().__init__()
        self.logger = logging.getLogger("global_logger")
        self.output_dir = "srv"
        self.config: Config = config
        self.client = OpenAI(
            base_url=self.config.openai_base_url,
            api_key=self.config.openai_api_key,
        )

        assert self.config.whisper is not None, (
            "validate_whisper_config ensures that even if old style whisper "
            + "config is given, it will be translated and config.whisper set."
        )

        if isinstance(self.config.whisper, TestWhisperConfig):
            self.transcriber = TestWhisperTranscriber(self.logger)
        elif isinstance(self.config.whisper, RemoteWhisperConfig):
            self.transcriber = RemoteWhisperTranscriber(
                self.logger, self.config.whisper
            )
        elif isinstance(self.config.whisper, LocalWhisperConfig):
            self.transcriber = LocalWhisperTranscriber(
                self.logger, self.config.whisper.model
            )
        else:
            raise ValueError(f"unhandled whisper config {config.whisper}")

    def process(self, post: Post, blocking: bool) -> str:
        locked = False
        working_paths = get_post_processed_audio_path(post)
        if working_paths is None:
            raise ProcessorException("Processed audio path not found")

        processed_audio_path = str(working_paths.post_processed_audio_path)
        with PodcastProcessor.lock_lock:
            if processed_audio_path not in PodcastProcessor.locks:
                PodcastProcessor.locks[processed_audio_path] = threading.Lock()
                PodcastProcessor.locks[
                    processed_audio_path
                ].acquire()  # should be no contention
                locked = True

        if not locked and not PodcastProcessor.locks[processed_audio_path].acquire(
            blocking=blocking
        ):
            raise ProcessorException("Processing job in progress")

        try:
            if os.path.exists(processed_audio_path):
                self.logger.info(f"Audio already processed: {post}")
                return processed_audio_path
            self.make_dirs(working_paths)
            transcript_segments = self.transcribe(post)
            user_prompt_template = self.get_user_prompt_template(
                self.config.processing.user_prompt_template_path
            )
            system_prompt = self.get_system_prompt(
                self.config.processing.system_prompt_path
            )
            self.classify(
                transcript_segments=transcript_segments,
                model=self.config.openai_model,
                system_prompt=system_prompt,
                user_prompt_template=user_prompt_template,
                num_segments_per_prompt=self.config.processing.num_segments_to_input_to_prompt,
                post=post,
                classification_path=working_paths.classification_dir,
            )
            ad_segments = self.get_ad_segments(
                transcript_segments, working_paths.classification_dir
            )
            audio = AudioSegment.from_file(post.unprocessed_audio_path)
            assert isinstance(audio, AudioSegment)
            self.create_new_audio_without_ads(
                audio=audio,
                ad_segments=ad_segments,
                min_ad_segment_length_seconds=self.config.output.min_ad_segment_length_seconds,
                min_ad_segement_separation_seconds=self.config.output.min_ad_segement_separation_seconds,  # pylint: disable=line-too-long
                fade_ms=self.config.output.fade_ms,
            ).export(processed_audio_path, format="mp3")
            self.logger.info(f"Processing podcast: {post} complete")
            post.processed_audio_path = processed_audio_path
            db.session.commit()

            return processed_audio_path
        finally:
            PodcastProcessor.locks[processed_audio_path].release()

    def make_dirs(self, processing_paths: ProcessingPaths) -> None:

        processing_paths.post_processed_audio_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        processing_paths.audio_processing_dir.mkdir(parents=True, exist_ok=True)
        processing_paths.classification_dir.mkdir(parents=True, exist_ok=True)

    def transcribe(self, post: Post) -> List[Segment]:
        # check db for transcript
        transcript = Transcript.query.filter_by(post_id=post.id).first()
        if transcript is not None:
            return cast(List[Segment], transcript.get_segments())

        segments = self.transcriber.transcribe(post.unprocessed_audio_path)

        for segment in segments:
            segment.start = round(segment.start, 1)
            segment.end = round(segment.end, 1)

        self.update_transcripts(post, segments)
        return segments

    def update_transcripts(self, post: Post, result: List[Segment]) -> None:
        post.transcript = Transcript(
            post_id=post.id,
            content=json.dumps([json.dumps(segment.dict()) for segment in result]),
        )
        db.session.commit()

    def get_system_prompt(self, system_prompt_path: str) -> str:
        with open(system_prompt_path, "r") as f:
            return f.read()

    def get_user_prompt_template(self, prompt_template_path: str) -> Template:
        with open(prompt_template_path, "r") as f:
            return Template(f.read())

    def classify(
        self,
        *,
        transcript_segments: List[Segment],
        model: str,
        system_prompt: str,
        user_prompt_template: Template,
        num_segments_per_prompt: int,
        post: Post,
        classification_path: Path,
    ) -> None:
        self.logger.info(f"Identifying ad segments for {post.unprocessed_audio_path}")
        self.logger.info(f"processing {len(transcript_segments)} transcript segments")

        for i in range(0, len(transcript_segments), num_segments_per_prompt):
            start = i
            end = min(i + num_segments_per_prompt, len(transcript_segments))

            target_dir = (
                classification_path
                / f"{transcript_segments[start].start}_{transcript_segments[end-1].end}"
            )
            identification_path = target_dir / "identification.txt"
            prompt_path = target_dir / "prompt.txt"
            target_dir.mkdir(exist_ok=True)

            # Check if we already have a valid identification
            if identification_path.exists():
                self.logger.info(
                    f"Responses for segments {start} to {end} already received"
                )
                continue

            excerpts = [
                f"[{segment.start}] {segment.text}"
                for segment in transcript_segments[start:end]
            ]

            if start == 0:
                excerpts.insert(0, "[TRANSCRIPT START]")
            elif end == len(transcript_segments):
                excerpts.append("[TRANSCRIPT END]")

            self.logger.info(f"Calling {model}")
            user_prompt = user_prompt_template.render(
                podcast_title=post.title,
                podcast_topic=post.description,
                transcript="\n".join(excerpts),
            )

            try:
                # Create a temporary file to indicate processing is in progress
                with open(f"{target_dir}/.in_progress", "w") as f:
                    f.write("Processing")

                identification = (
                    None
                    if isinstance(self.config.whisper, TestWhisperConfig)
                    else self.call_model(model, system_prompt, user_prompt)
                )
                if identification:
                    with open(identification_path, "w") as f:
                        f.write(identification)
                    with open(prompt_path, "w") as f:
                        f.write(user_prompt)
                else:
                    self.logger.error(
                        f"Failed to get identification for segments {start} to {end}"
                    )
                    # Create an empty identification file to prevent endless retries
                    with open(f"{target_dir}/identification.txt", "w") as f:
                        f.write('{"ad_segments": [], "confidence": 0.0}')
            finally:
                # Clean up the in_progress file
                if os.path.exists(f"{target_dir}/.in_progress"):
                    os.remove(f"{target_dir}/.in_progress")

    def call_model(
        self, model: str, system_prompt: str, user_prompt: str, max_retries: int = 3
    ) -> Optional[str]:
        attempt = 0
        last_error = None

        while attempt < max_retries:
            try:
                self.logger.info(
                    f"Calling model: {model} (attempt {attempt + 1}/{max_retries})"
                )
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=self.config.openai_max_tokens,
                    timeout=self.config.openai_timeout,
                )

                content = response.choices[0].message.content
                assert content is not None
                return content

            except APIError as e:
                last_error = e
                self.logger.error(f"OpenAI API error (attempt {attempt + 1}): {e}")
                if getattr(e, "code", None) == 500:
                    # Add exponential backoff for retries
                    wait_time = (2**attempt) * 1  # 1, 2, 4 seconds
                    time.sleep(wait_time)
                    attempt += 1
                    continue
                # For non-500 errors, raise immediately
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error calling model: {e}")
                raise

        # If we get here, we've exhausted our retries
        self.logger.error(f"Failed to call model after {max_retries} attempts")
        if last_error:
            raise last_error
        return None

    def get_ad_segments(
        self, segments: List[Segment], classification_path_path: Path
    ) -> List[Tuple[float, float]]:
        classification_path = str(classification_path_path)
        segments_by_start = {segment.start: segment for segment in segments}
        ad_segments = []
        for classification_dir in sorted(
            os.listdir(classification_path),
            key=lambda filename: (len(filename), filename),
        ):
            try:
                with open(
                    f"{classification_path}/{classification_dir}/identification.txt",
                    "r",
                ) as id_file:
                    prompt_start_timestamp = float(classification_dir.split("_")[0])
                    prompt_end_timestamp = float(classification_dir.split("_")[1])
                    identification = id_file.read()

                    try:
                        prediction = clean_and_parse_model_output(identification)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        self.logger.error(
                            f"Error parsing ad segment: {e} for {identification}"
                        )
                        continue

                    if prediction.confidence < self.config.output.min_confidence:
                        continue

                    ad_segment_starts = prediction.ad_segments
                    # filter out ad segments outside of the start/end, and that
                    # do not exist in segments_by_start
                    ad_segment_starts = [
                        start
                        for start in ad_segment_starts
                        if start  # pylint: disable=chained-comparison
                        >= prompt_start_timestamp
                        and start <= prompt_end_timestamp
                        and start in segments_by_start
                    ]

                    for ad_segment_start in ad_segment_starts:
                        ad_segment_end = segments_by_start[ad_segment_start].end
                        ad_segments.append((ad_segment_start, ad_segment_end))
            except FileNotFoundError:
                self.logger.error(
                    f"Identification file not found for {classification_dir}"
                )

        return ad_segments

    def get_ad_fade_out(
        self, audio: AudioSegment, ad_start_ms: int, fade_ms: int
    ) -> AudioSegment:
        fade_out = audio[ad_start_ms : ad_start_ms + fade_ms]
        assert isinstance(fade_out, AudioSegment)

        fade_out = fade_out.fade_out(fade_ms)
        return fade_out

    def get_ad_fade_in(
        self, audio: AudioSegment, ad_end_ms: int, fade_ms: int
    ) -> AudioSegment:
        fade_in = audio[ad_end_ms - fade_ms : ad_end_ms]
        assert isinstance(fade_in, AudioSegment)

        fade_in = fade_in.fade_in(fade_ms)
        return fade_in

    def create_new_audio_without_ads(
        self,
        *,
        audio: AudioSegment,
        ad_segments: List[Tuple[float, float]],
        min_ad_segment_length_seconds: int,
        min_ad_segement_separation_seconds: int,
        fade_ms: int = 5000,
    ) -> AudioSegment:
        self.logger.info(
            f"Creating new audio with ads segments removed between: {ad_segments}"
        )
        # if any two ad segments overlap by fade_ms, join them into single segment
        ad_segments = sorted(ad_segments)
        i = 0
        while i < len(ad_segments) - 1:
            if (
                ad_segments[i][1] + min_ad_segement_separation_seconds
                >= ad_segments[i + 1][0]
            ):
                ad_segments[i] = (ad_segments[i][0], ad_segments[i + 1][1])
                ad_segments.pop(i + 1)
            else:
                i += 1

        # remove any isloated ad segments that are too short, possibly misidentified
        ad_segments = [
            segment
            for segment in ad_segments
            if segment[1] - segment[0] >= min_ad_segment_length_seconds
        ]
        # whisper sometimes drops the last bit of the transcript & this can lead
        # to end-roll not being entirely removed, so bump the ad segment to the
        # end of the audio if it's close enough
        if len(ad_segments) > 0:
            if (
                audio.duration_seconds - ad_segments[-1][1]
                < min_ad_segement_separation_seconds
            ):
                ad_segments[-1] = (ad_segments[-1][0], audio.duration_seconds)
        self.logger.info(f"Joined ad segments into: {ad_segments}")

        ad_segments_ms = [
            (int(start * 1000), int(end * 1000)) for start, end in ad_segments
        ]
        new_audio = AudioSegment.empty()
        last_end = 0
        for start, end in ad_segments_ms:
            new_audio += audio[last_end:start]
            new_audio += self.get_ad_fade_out(audio, start, fade_ms)
            new_audio += self.get_ad_fade_in(audio, end, fade_ms)
            last_end = end
            gc.collect()
        if last_end != audio.duration_seconds * 1000:
            new_audio += audio[last_end:]
        return new_audio


class ProcessorException(Exception):
    pass
