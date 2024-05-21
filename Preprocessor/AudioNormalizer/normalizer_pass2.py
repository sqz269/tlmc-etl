import json
import os
import subprocess
from dataclasses import dataclass
from typing import Dict

import Preprocessor.AudioNormalizer.output.path_definitions as AudioNormalizerOutputPaths
from Preprocessor.AudioNormalizer.normalizer_pass1 import (
    NORMALIZATION_TARGET,
    NormalizationParameters,
    Stage1WorkResult,
)
from Shared.reporting_multi_processor import (
    JournalWriter,
    OutputWriter,
    PrintMessageReporter,
    StatAutoMuxMultiProcessor,
)
from Shared.utils import get_file_relative, get_output_path, oslex_quote

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


class Stage2:
    @staticmethod
    def make_ffmpeg_norm_param_cmd(src: str, dst: str, params: NormalizationParameters):
        return [
            "ffmpeg",
            "-i",
            oslex_quote(src),
            "-af",
            f"loudnorm=I={NORMALIZATION_TARGET['I']}:TP={NORMALIZATION_TARGET['TP']}:LRA={NORMALIZATION_TARGET['LRA']}:measured_I={params.measured_i}:measured_LRA={params.measured_lra}:measured_TP={params.measured_tp}:measured_thresh={params.measured_thresh}:offset={params.target_offset}:linear=true",
            "-sample_fmt",
            params.target_sample_fmt,
            oslex_quote(dst),
            "-y",
            "-v",
            "quiet",
            "-stats",
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

            # replace the original file with the normalized one
            dst = work["dst"]
            src = work["src"]
            os.remove(src)
            os.rename(dst, src)

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
            os.cpu_count() // 4,
            journal_writer,
            output_writer,
        )

        for file, cmd in worklist.items():
            processor.submit_job(Stage2.process_one, file, cmd)

        processor.wait_print_complete()
        processor.reset_terminal()


if __name__ == "__main__":
    Stage2.start()
