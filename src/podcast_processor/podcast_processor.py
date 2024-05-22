import threading
import logging
import whisper
from pydub import AudioSegment
import os
import json
from openai import OpenAI
from jinja2 import Template
import pickle
import threading
import time
from dotenv import dotenv_values

env = dotenv_values( ".env" )
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
            transcript = self.transcribe(
                task,
                transcript_dir,
            )
            user_prompt_template = self.get_user_prompt_template(
                self.config["processing"]["user_prompt_template_path"]
            )
            self.classify(
                transcript,
                env.OPENAI_MODEL_NAME or "gpt-4o",
                self.config["processing"]["system_prompt"],
                user_prompt_template,
                self.config["processing"]["num_segments_to_input_to_prompt"],
                task,
                classification_dir,
            )
            ad_segments = self.get_ad_segments(
                transcript["segments"], classification_dir
            )
            audio = AudioSegment.from_file(task.audio_path)
            self.create_new_audio_without_ads(
                audio,
                ad_segments,
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
            return self.pickle_transcripts[task.pickle_id()]

        # log available models
        models = whisper.available_models()
        self.logger.info(f"Available models: {models}")

        model = whisper.load_model(
            name=env.WHISPER_MODEL or "base",
        )

        self.logger.info("Beginning transcription")
        start = time.time()
        result = model.transcribe(task.audio_path, fp16=False, language="English")
        end = time.time()
        elapsed = end - start
        self.logger.info(f"Transcription completed in {elapsed}")

        for segment in result["segments"]:
            segment["start"] = round(segment["start"], 1)
            segment["end"] = round(segment["end"], 1)

        with open(transcript_file_path + "/transcript.txt", "w") as f:
            for segment in result["segments"]:
                f.write(f"{segment['start']}{segment['text']}\n")

        self.update_pickle_transcripts(task, result)
        return result

    def get_user_prompt_template(self, prompt_template_path):
        with open(prompt_template_path, "r") as f:
            return Template(f.read())

    def classify(
        self,
        transcript,
        model,
        system_prompt,
        user_prompt_template,
        num_segments_to_input_to_prompt,
        task,
        classification_path,
    ):
        self.logger.info(f"Identifying ad segments for {task.audio_path}")
        if os.listdir(classification_path):
            self.logger.info("Audio already classified")
            return

        segments = transcript["segments"]
        self.logger.info(f"processing {len(segments)} transcript segments")
        for i in range(0, len(segments), num_segments_to_input_to_prompt):
            start = i
            end = min(i + num_segments_to_input_to_prompt, len(segments))

            target_dir = f"{classification_path}/{segments[start]['start']}_{segments[end-1]['end']}"
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            else:
                self.logger.info(
                    f"Responses for segments {start} to {end} already received"
                )
                continue
            excerpts = [
                f"[{segment['start']}] {segment['text']}"
                for segment in segments[start:end]
            ]

            if start == 0:
                excerpts.insert(0, f"[TRANSCRIPT START]")
            elif end == len(segments):
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
        client = OpenAI(
            base_url=env.OPENAI_BASE_URL or "https://api.openai.com/v1",
            api_key=env.OPENAI_API_KEY,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=env.OPENAI_MAX_TOKENS,
            timeout=env.OPENAI_TIMEOUT,
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
        self, audio, ad_segments, min_ad_segement_separation_seconds, fade_ms=5000
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
        self.logger.info(f"Joined ad segments into: {ad_segments}")
        ad_segments_ms = [(start * 1000, end * 1000) for start, end in ad_segments]
        new_audio = AudioSegment.empty()
        last_end = 0
        for start, end in ad_segments_ms:
            new_audio += audio[last_end:start]
            new_audio += self.get_ad_fade_out(audio, start, fade_ms)
            new_audio += self.get_ad_fade_in(audio, end, fade_ms)
            last_end = end
        new_audio += audio[last_end:]
        return new_audio


if __name__ == "__main__":
    import queue
    import logging
    import yaml

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("global_logger")

    with open("config/config.yml", "r") as f:
        config = yaml.safe_load(f)

    queue = queue.Queue()
    task = PodcastProcessorTask(
        "Example",
        "in/example.mp3",
        "Example podcast title",
    )
    queue.put(task)
    processor = PodcastProcessor(queue, config)
    processor.process(task)
    logger.info("PodcastProcessor done")
