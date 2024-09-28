import threading
import logging
from pydub import AudioSegment
import os
import json
from openai import OpenAI
from jinja2 import Template
import pickle
import threading
import time
import gc
import math
import shutil
from dotenv import dotenv_values

env = dotenv_values(".env")
for key in env:
    if key == "OPENAI_API_KEY":
        print(key, "********")
    else:
        print(key, env[key])


class PodcastProcessorTask:
    def __init__(self, podcast_title, audio_path, podcast_description):
        self.podcast_title = podcast_title
        self.audio_path = audio_path
        self.podcast_description = podcast_description

    def pickle_id(self):
        return f"{self.podcast_title}_{self.audio_path}"

    def __str__(self):
        return f"ProcessTask: {self.audio_path}"

    def get_output_path(self):
        return f"srv/{self.podcast_title}/{self.audio_path.split('/')[-1]}"


class PodcastProcessor:
    lock_lock = threading.Lock()
    locks = {}

    def __init__(self, config, processing_dir="processing"):
        super().__init__()
        self.logger = logging.getLogger("global_logger")
        self.processing_dir = processing_dir
        self.output_dir = "srv"
        self.config = config
        self.pickle_transcripts = self.init_pickle_transcripts()
        self.client = OpenAI(
            base_url=(
                env["OPENAI_BASE_URL"]
                if "OPENAI_BASE_URL" in env
                else "https://api.openai.com/v1"
            ),
            api_key=env["OPENAI_API_KEY"],
        )

    def init_pickle_transcripts(self):
        pickle_path = "transcripts.pickle"
        if not os.path.exists(pickle_path):
            with open(pickle_path, "wb") as f:
                pickle.dump({}, f)
                return {}
        else:
            with open(pickle_path, "rb") as f:
                return pickle.load(f)

    def update_pickle_transcripts(self, task, result):
        with open("transcripts.pickle", "wb") as f:
            self.pickle_transcripts[task.pickle_id()] = result
            pickle.dump(self.pickle_transcripts, f)

    def process(self, task):
        with PodcastProcessor.lock_lock:
            if task.get_output_path() not in PodcastProcessor.locks:
                PodcastProcessor.locks[task.get_output_path()] = threading.Lock()

        with PodcastProcessor.locks[task.get_output_path()]:
            if os.path.exists(task.get_output_path()):
                self.logger.info(f"Audio already processed: {task}")
                return task.get_output_path()
            transcript_dir, classification_dir, final_audio_path = self.make_dirs(task)
            transcript_segments = self.transcribe(
                task,
                transcript_dir,
            )
            user_prompt_template = self.get_user_prompt_template(
                self.config["processing"]["user_prompt_template_path"]
            )
            system_prompt = self.get_system_prompt(self.config["processing"]["system_prompt_path"])
            self.classify(
                transcript_segments,
                env["OPENAI_MODEL"] if "OPENAI_MODEL" in env else "gpt-4o",
                system_prompt,
                user_prompt_template,
                self.config["processing"]["num_segments_to_input_to_prompt"],
                task,
                classification_dir,
            )
            ad_segments = self.get_ad_segments(transcript_segments, classification_dir)
            audio = AudioSegment.from_file(task.audio_path)
            self.create_new_audio_without_ads(
                audio,
                ad_segments,
                self.config["output"]["min_ad_segment_length_seconds"],
                self.config["output"]["min_ad_segement_separation_seconds"],
                self.config["output"]["fade_ms"],
            ).export(
                f'{final_audio_path}/{task.audio_path.split("/")[-1]}', format="mp3"
            )
            self.logger.info(f"Processing task: {task} complete")
            return task.get_output_path()

    def make_dirs(self, task):
        audio_processing_dir = f'{self.processing_dir}/{task.podcast_title}/{task.audio_path.split("/")[-1]}'
        transcript_dir = f"{audio_processing_dir}/transcription"
        classification_dir = f"{audio_processing_dir}/classification"
        final_audio_path = f"{self.output_dir}/{task.podcast_title}"
        if not os.path.exists(final_audio_path):
            os.makedirs(final_audio_path)
        if not os.path.exists(audio_processing_dir):
            os.makedirs(audio_processing_dir)
        if not os.path.exists(transcript_dir):
            os.makedirs(transcript_dir)
        if not os.path.exists(classification_dir):
            os.makedirs(classification_dir)
        return transcript_dir, classification_dir, final_audio_path

    def transcribe(
        self,
        task,
        transcript_file_path,
    ):
        self.logger.info(
            f"Transcribing audio from {task.audio_path} into {transcript_file_path}"
        )
        # check pickle
        if task.pickle_id() in self.pickle_transcripts:
            self.logger.info("Transcript already transcribed")
            transcript = self.pickle_transcripts[task.pickle_id()]
            if (
                "segments" in transcript
            ):  # used to store whole transcript, saves people from having to delete pickle on upgrade
                return transcript["segments"]
            else:
                return transcript

        segments = (
            self.remote_whisper(task)
            if "REMOTE_WHISPER" in env
            else self.local_whisper(task)
        )

        for segment in segments:
            segment["start"] = round(segment["start"], 1)
            segment["end"] = round(segment["end"], 1)

        with open(transcript_file_path + "/transcript.txt", "w") as f:
            for segment in segments:
                f.write(f"{segment['start']}{segment['text']}\n")

        self.update_pickle_transcripts(task, segments)
        return segments

    def remote_whisper(self, task):
        self.logger.info("Using remote whisper")
        self.split_file(task.audio_path)
        for i in range(0, len(os.listdir(f"{task.audio_path}_parts")), 1):
            segments = self.get_segments_for_chunk(f"{task.audio_path}_parts/{i}.mp3")
            if i == 0:
                all_segments = segments
            else:
                all_segments.extend(segments)
        # clean up
        shutil.rmtree(f"{task.audio_path}_parts")
        return all_segments

    def get_segments_for_chunk(self, chunk):
        with open(chunk, "rb") as f:
            return self.client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                timestamp_granularities=["segment"],
                language="en",
                response_format="verbose_json",
            ).model_extra["segments"]

    def split_file(
        self, audio_path, chunk_size=24 * 1024 * 1024
    ):  # chunk_size in bytes
        if not os.path.exists(audio_path + "_parts"):
            os.makedirs(audio_path + "_parts")
        audio = AudioSegment.from_mp3(audio_path)
        duration = len(audio)  # duration in milliseconds
        chunk_duration = (
            chunk_size / os.path.getsize(audio_path)
        ) * duration  # chunk duration in milliseconds

        num_chunks = math.ceil(duration / chunk_duration)
        for i in range(num_chunks):
            start_time = i * chunk_duration
            end_time = (i + 1) * chunk_duration
            chunk = audio[start_time:end_time]
            chunk.export(f"{audio_path}_parts/{i}.mp3", format="mp3")

    def local_whisper(self, task):
        import whisper

        self.logger.info("Using local whisper")
        models = whisper.available_models()
        self.logger.info(f"Available models: {models}")

        model = whisper.load_model(
            name=env["WHISPER_MODEL"] if "WHISPER_MODEL" in env else "base",
        )

        self.logger.info("Beginning transcription")
        start = time.time()
        result = model.transcribe(task.audio_path, fp16=False, language="English")
        end = time.time()
        elapsed = end - start
        self.logger.info(f"Transcription completed in {elapsed}")
        return result["segments"]
    
    def get_system_prompt(self, system_prompt_path):
        with open(system_prompt_path, "r") as f:
            return f.read()

    def get_user_prompt_template(self, prompt_template_path):
        with open(prompt_template_path, "r") as f:
            return Template(f.read())

    def classify(
        self,
        transcript_segments,
        model,
        system_prompt,
        user_prompt_template,
        num_segments_to_input_to_prompt,
        task,
        classification_path,
    ):
        self.logger.info(f"Identifying ad segments for {task.audio_path}")
        self.logger.info(f"processing {len(transcript_segments)} transcript segments")
        for i in range(0, len(transcript_segments), num_segments_to_input_to_prompt):
            start = i
            end = min(i + num_segments_to_input_to_prompt, len(transcript_segments))

            target_dir = f"{classification_path}/{transcript_segments[start]['start']}_{transcript_segments[end-1]['end']}"
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            else:
                self.logger.info(
                    f"Responses for segments {start} to {end} already received"
                )
                continue
            excerpts = [
                f"[{segment['start']}] {segment['text']}"
                for segment in transcript_segments[start:end]
            ]

            if start == 0:
                excerpts.insert(0, f"[TRANSCRIPT START]")
            elif end == len(transcript_segments):
                excerpts.append(f"[TRANSCRIPT END]")

            self.logger.info(f"Calling {model}")
            user_prompt = user_prompt_template.render(
                podcast_title=task.podcast_title,
                podcast_topic=task.podcast_description,
                transcript="\n".join(excerpts),
            )
            identification = self.call_model(model, system_prompt, user_prompt)
            with open(f"{target_dir}/identification.txt", "w") as f:
                f.write(identification)
            with open(f"{target_dir}/prompt.txt", "w") as f:
                f.write(user_prompt)

    def call_model(self, model, system_prompt, user_prompt):
        # log the request
        self.logger.info(f"Calling model: {model}")
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=env["OPENAI_MAX_TOKENS"] if "OPENAI_MAX_TOKENS" in env else 4096,
            timeout=env["OPENAI_TIMEOUT"] if "OPENAI_TIMEOUT" in env else 300,
        )

        return response.choices[0].message.content

    def get_ad_segments(self, segments, classification_path):
        segments_by_start = {segment["start"]: segment for segment in segments}
        ad_segments = []
        for dir in sorted(
            os.listdir(classification_path),
            key=lambda filename: (len(filename), filename),
        ):
            with open(f"{classification_path}/{dir}/identification.txt", "r") as f:
                prompt_start_timestamp = float(dir.split("_")[0])
                prompt_end_timestamp = float(dir.split("_")[1])
                identification = f.read()
                identification = identification.replace("```json", "")
                identification = identification.replace("```", "")
                identification = identification.replace("'", '"')
                identification = identification.replace("\n", "")
                identification = identification.strip()
                try:
                    identification_json = json.loads(identification)
                    if "confidence" in identification_json:
                        confidence = identification_json["confidence"]
                        if confidence < self.config["output"]["min_confidence"]:
                            continue
                    ad_segment_starts = identification_json["ad_segments"]
                    # filter out ad segments outside of the start/end, and that do not exist in segments_by_start
                    ad_segment_starts = [
                        start
                        for start in ad_segment_starts
                        if start >= prompt_start_timestamp
                        and start <= prompt_end_timestamp
                        and start in segments_by_start
                    ]
                    if len(ad_segment_starts) == 0:
                        continue
                    for ad_segment_start in ad_segment_starts:
                        ad_segment_end = segments_by_start[ad_segment_start]["end"]
                        ad_segments.append((ad_segment_start, ad_segment_end))
                except Exception as e:
                    self.logger.error(
                        f"Error parsing ad segment: {e} for {identification}"
                    )
        return ad_segments

    def get_ad_fade_out(self, audio, start, fade_ms):
        fade_out = audio[start : start + fade_ms]
        fade_out = fade_out.fade_out(fade_ms)
        return fade_out

    def get_ad_fade_in(self, audio, ad_end, fade_ms):
        fade_in = audio[ad_end - fade_ms : ad_end]
        fade_in = fade_in.fade_in(fade_ms)
        return fade_in

    def create_new_audio_without_ads(
        self,
        audio,
        ad_segments,
        min_ad_segment_length_seconds,
        min_ad_segement_separation_seconds,
        fade_ms=5000,
    ):
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
        # whisper sometimes drops the last bit of the transcript & this can lead to end-roll not being
        # entirely removed, so bump the ad segment to the end of the audio if it's close enough
        if len(ad_segments) > 0:
            if (
                audio.duration_seconds - ad_segments[-1][1]
                < min_ad_segement_separation_seconds
            ):
                ad_segments[-1] = (ad_segments[-1][0], audio.duration_seconds)
        self.logger.info(f"Joined ad segments into: {ad_segments}")

        ad_segments_ms = [(start * 1000, end * 1000) for start, end in ad_segments]
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


if __name__ == "__main__":
    import logging
    import yaml

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("global_logger")

    with open("config/config.yml", "r") as f:
        config = yaml.safe_load(f)

    task = PodcastProcessorTask(
        "Example",
        "in/example.mp3",
        "Example podcast title",
    )
    processor = PodcastProcessor(config)
    processor.process(task)
    logger.info("PodcastProcessor done")
