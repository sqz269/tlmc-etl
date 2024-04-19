from dataclasses import dataclass
import json
import os
import subprocess
from typing import Dict
from Shared.utils import get_file_relative, oslex_quote, get_output_path
from Shared.reporting_multi_processor import (
    JournalWriter,
    OutputWriter,
    PrintMessageReporter,
    StatAutoMuxMultiProcessor,
)
import Preprocessor.AudioNormalizer.output.path_definitions as AudioNormalizerOutputPaths

FILE_EXT = (".flac", ".wav", ".mp3", ".m4a")

stage_1_worklist = get_output_path(
    AudioNormalizerOutputPaths,
    AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_WORKLIST_PATH,
)

stage_1_output = get_output_path(
    AudioNormalizerOutputPaths,
    AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_OUTPUT_FILELIST_NAME,
)

stage_2_worklist = get_output_path(
    AudioNormalizerOutputPaths,
    AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_WORKLIST_PATH,
)

stage_2_output = get_output_path(
    AudioNormalizerOutputPaths,
    AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_COMPLETED_NAME,
)


@dataclass
class NormalizationParameters:
    measured_i: int
    measured_tp: float
    measured_lra: float
    measured_thresh: float
    target_offset: float
    target_sample_fmt: str = "s16"

    def to_json(self):
        return {
            "measured_i": self.measured_i,
            "measured_tp": self.measured_tp,
            "measured_lra": self.measured_lra,
            "measured_thresh": self.measured_thresh,
            "target_offset": self.target_offset,
            "target_sample_fmt": self.target_sample_fmt,
        }

    @staticmethod
    def from_json(json_obj):
        return NormalizationParameters(
            measured_i=json_obj["measured_i"],
            measured_tp=json_obj["measured_tp"],
            measured_lra=json_obj["measured_lra"],
            measured_thresh=json_obj["measured_thresh"],
            target_offset=json_obj["target_offset"],
            target_sample_fmt=json_obj["target_sample_fmt"],
        )


@dataclass
class Stage1WorkResult:
    path: str
    normalization_params: NormalizationParameters

    def to_json(self):
        return {
            "path": self.path,
            "normalization_params": self.normalization_params.to_json(),
        }

    @staticmethod
    def from_json(json_obj) -> "Stage1WorkResult":
        return Stage1WorkResult(
            path=json_obj["path"],
            normalization_params=NormalizationParameters.from_json(
                json_obj["normalization_params"]
            ),
        )


class Stage2:
    @staticmethod
    def make_ffmpeg_norm_param_cmd(src: str, dst: str, params: NormalizationParameters):
        # ffmpeg -i in.wav -af loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-27.61:measured_LRA=18.06:measured_TP=-4.47:measured_thresh=-39.20:offset=0.58:linear=true:print_format=summary -ar 48k out.wav
        return [
            "ffmpeg",
            "-i",
            oslex_quote(src),
            "-af",
            f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={params.measured_i}:measured_LRA={params.measured_lra}:measured_TP={params.measured_tp}:measured_thresh={params.measured_thresh}:offset={params.target_offset}:linear=true",
            "-sample_fmt",
            params.target_sample_fmt,
            oslex_quote(dst),
            "-y",
            "-v",
            "quiet",
            "-stats",
        ]

    @staticmethod
    def make_ffprobe_get_sample_format_cmd(src: str):
        return [
            "ffprobe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            "-i",
            oslex_quote(src),
            "-hide_banner",
            "-v",
            "quiet",
        ]

    @staticmethod
    def make_tmp_dst_name(src: str):
        base = os.path.basename(src)
        path = os.path.dirname(src)
        return os.path.join(path, f"audio.norm.{base}")

    @staticmethod
    def generate_stage_2_work_list():
        stage_2_worklist = {}
        with open(stage_1_output, "r", encoding="utf-8") as f:
            results = [
                Stage1WorkResult.from_json(json.loads(line)) for line in f.readlines()
            ]

        for result in results:
            tmp_dst = Stage2.make_tmp_dst_name(result.path)
            stage_2_worklist[result.path] = {
                "src": result.path,
                "dst": tmp_dst,
                "params": result.normalization_params.to_json(),
                "cmd": " ".join(
                    Stage2.make_ffmpeg_norm_param_cmd(
                        result.path, tmp_dst, result.normalization_params
                    ),
                ),
            }

        return stage_2_worklist

    @staticmethod
    def filter_completed(worklist: Dict[str, str]):
        completed = []
        if not os.path.exists(stage_2_output):
            return worklist

        # output is json file, each line is a json document
        # with sturcture of {path: <path>}
        with open(stage_2_output, "r", encoding="utf-8") as f:
            completed = [
                json.loads(line) for line in f.readlines() if line.strip() != ""
            ]

        return {k: v for k, v in worklist.items() if k not in completed}

    @staticmethod
    def process_one(
        journalWriter: JournalWriter,
        messageWriter: PrintMessageReporter,
        outputWriter: OutputWriter,
        file: str,
        work: dict,
    ):
        try:
            messageWriter.report_state(f"Processing {file}")

            proc = subprocess.Popen(
                work["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                shell=True,
            )

            proc.wait()

            if proc.returncode != 0:
                journalWriter.report_error(
                    f"Failed to process {file} with command [{work['cmd']}]. Process returned code {proc.returncode}\n"
                )
                return

            outputWriter.write(json.dumps({"path": file}, ensure_ascii=False) + "\n")
            journalWriter.report_completed(f"Completed {file}\n")
        except Exception as e:
            journalWriter.report_error(
                f"Failed to process {file} with command [{work['cmd']}]\n"
            )

    @staticmethod
    def start():
        if not os.path.isfile(stage_1_output):
            print("Stage 1 output not found, exiting")
            return

        if not os.path.exists(stage_2_worklist):
            print("Stage 2 output not found, generating worklist")
            worklist = Stage2.generate_stage_2_work_list()
            with open(stage_2_worklist, "w", encoding="utf-8") as f:
                json.dump(worklist, f, ensure_ascii=False)

        with open(stage_2_worklist, "r", encoding="utf-8") as f:
            worklist = json.load(f)
            print("Loaded worklist ({} items)".format(len(worklist)))

        print("Filtering completed work")
        worklist = Stage2.filter_completed(worklist)

        print("Processing worklist")

        journal_path_fail = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_FAILED_NAME,
        )

        journal_path = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_JOURNAL_NAME,
        )

        journal_path_completed = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_JOURNAL_NAME,
        )

        journal_writer = JournalWriter(
            journal_path, journal_path_fail, journal_path_completed
        )

        output_path = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_SECOND_PASS_CONVERT_COMPLETED_NAME,
        )

        output_writer = OutputWriter(output_path)

        processor = StatAutoMuxMultiProcessor(
            os.cpu_count() // 2,
            journal_writer,
            output_writer,
        )

        for file, cmd in worklist.items():
            processor.submit_job(Stage2.process_one, file, cmd)

        processor.wait_print_complete()
        processor.reset_terminal()


class Stage1:

    @staticmethod
    def make_ffmpeg_cmd(src):
        return [
            "ffmpeg",
            "-i",
            oslex_quote(src),
            "-af",
            "loudnorm=I=-24:LRA=7:tp=-2.0:print_format=json",
            "-f",
            "null",
            "-",
            "-y",
            # "-v",
            # "quiet",
        ]

    @staticmethod
    def generate_stage_1_work_list(root):
        filelist = {}
        for root, dirs, files in os.walk(root):
            for file in files:
                if file.endswith(FILE_EXT):
                    fp = os.path.join(root, file)
                    stage_1_cmd = Stage1.make_ffmpeg_cmd(fp)
                    filelist[fp] = " ".join(stage_1_cmd)

        return filelist

    @staticmethod
    def filter_completed(worklist: Dict[str, str]):
        completed = []
        if not os.path.exists(stage_1_output):
            return worklist

        with open(stage_1_output, "r", encoding="utf-8") as f:
            completed = [
                Stage1WorkResult.from_json(json.loads(line)) for line in f.readlines()
            ]
            completed = set([result.path for result in completed])

        return {k: v for k, v in worklist.items() if k not in completed}

    def find_json_output(lines: list[str]):
        stripped = [line.strip() for line in lines]
        end = stripped.index("}")
        reversed = stripped[::-1]
        start = len(reversed) - reversed.index("{") - 1

        return "\n".join(stripped[start : end + 1])

    @staticmethod
    def process_one(
        journalWriter: JournalWriter,
        messageWriter: PrintMessageReporter,
        outputWriter: OutputWriter,
        file: str,
        cmd: str,
    ):
        try:
            messageWriter.report_state(f"Processing {file}")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                shell=True,
            )

            proc.wait()

            if proc.returncode != 0:
                journalWriter.report_error(
                    f"Failed to process {file} with command [{cmd}]. Process returned code {proc.returncode}\n"
                )
                return

            results_str = proc.stdout.read()
            results_json = json.loads(Stage1.find_json_output(results_str.split("\n")))

            # Get the file's sample format as by default the loutnorm filter will output s32
            cmd = " ".join(
                Stage2.make_ffprobe_get_sample_format_cmd(file),
            )

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                shell=True,
            )

            proc.wait()

            if proc.returncode != 0:
                journalWriter.report_error(
                    f"Failed to process {file} with command [{cmd}]. Process returned code {proc.returncode}\n"
                )
                return

            sample_fmt_str = proc.stdout.read()
            sample_fmt_json = json.loads(sample_fmt_str)
            sample_fmt = "s16"
            for stream in sample_fmt_json["streams"]:
                if stream["codec_type"] == "audio":
                    if "sample_fmt" in stream:
                        sample_fmt = stream["sample_fmt"]
                    break

            params = NormalizationParameters(
                measured_i=results_json["input_i"],
                measured_tp=results_json["input_tp"],
                measured_lra=results_json["input_lra"],
                measured_thresh=results_json["input_thresh"],
                target_offset=results_json["target_offset"],
                target_sample_fmt=sample_fmt,
            )

            output = Stage1WorkResult(
                path=file,
                normalization_params=params,
            )

            outputWriter.write(json.dumps(output.to_json(), ensure_ascii=False) + "\n")
            journalWriter.report_completed(f"Completed {file}\n")
        except Exception as e:
            journalWriter.report_error(
                f"Failed to process {file} with command [{cmd}]\n"
            )

    @staticmethod
    def start(root: str):
        if not os.path.exists(stage_1_worklist):
            print("Stage 1 worklist not exist, generating...")
            worklist = Stage1.generate_stage_1_work_list(root)
            print("Writing worklist to disk")
            with open(stage_1_worklist, "w", encoding="utf-8") as f:
                json.dump(worklist, f, ensure_ascii=False)

        with open(stage_1_worklist, "r", encoding="utf-8") as f:
            worklist = json.load(f)
            print("Loaded worklist ({} items)".format(len(worklist)))

        print("Filtering completed work")
        worklist = Stage1.filter_completed(worklist)

        print("Processing worklist")

        journal_path_fail = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_FAILED_NAME,
        )

        journal_path = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_JOURNAL_NAME,
        )

        journal_path_completed = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_JOURNAL_NAME,
        )

        journal_writer = JournalWriter(
            journal_path, journal_path_fail, journal_path_completed
        )

        output_path = get_output_path(
            AudioNormalizerOutputPaths,
            AudioNormalizerOutputPaths.NORMALIZE_FIRST_PASS_DETECT_OUTPUT_FILELIST_NAME,
        )

        output_writer = OutputWriter(output_path)

        processor = StatAutoMuxMultiProcessor(
            os.cpu_count() // 2,
            journal_writer,
            output_writer,
        )

        for file, cmd in worklist.items():
            processor.submit_job(Stage1.process_one, file, cmd)

        processor.wait_print_complete()
        processor.reset_terminal()


if __name__ == "__main__":
    tlmc_root = input("Enter TLMC root path: ")
    Stage1.start(tlmc_root)

    Stage2.start()
