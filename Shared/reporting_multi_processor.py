from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from os import PathLike
import os
import threading
from typing import Any, Callable, List


class JournalWriter:
    journal_lock = threading.Lock()
    journal_failed_lock = threading.Lock()
    journal_completed_lock = threading.Lock()

    def __init__(
        self, journal: str, journal_failed: str, journal_completed: str
    ) -> None:
        all_paths: List[str] = [
            journal,
            journal_failed,
            journal_completed,
        ]

        self.stats = {
            "completed": 0,
            "failed": 0,
        }

        for path in all_paths:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    pass

        self.journal = open(journal, "a+", encoding="utf-8")
        self.journal_failed = open(journal_failed, "a+", encoding="utf-8")
        self.journal_completed = open(journal_completed, "a+", encoding="utf-8")

    def report_error(self, msg):
        with self.journal_failed_lock:
            self.stats["failed"] += 1
            self.journal_failed.write(msg)
            self.journal_failed.flush()

    def report_completed(self, msg):
        with self.journal_completed_lock:
            self.stats["completed"] += 1
            self.journal_completed.write(msg)
            self.journal_completed.flush()

    def report(self, msg):
        with self.journal_lock:
            self.journal.write(msg)
            self.journal.flush()


class OutputWriter:
    lock = threading.Lock()

    def __init__(self, path: str) -> None:
        self.path = path

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                pass

        self.file = open(path, "a+", encoding="utf-8")

    def write(self, output):
        with self.lock:
            self.file.write(output)
            self.file.flush()


class PrintMessageReporter:

    def __init__(self) -> None:
        self.message = {}

    def report_state(self, msg):
        # Get the identity of the reporting thread
        # and report the message
        identity = threading.get_ident()
        self.message[identity] = msg


class StatAutoMuxMultiProcessor:

    def __init__(
        self,
        num_processors: int,
        journal_writer: JournalWriter,
        output_writer: OutputWriter,
    ):
        self.num_processors = num_processors
        self.executor = ThreadPoolExecutor(max_workers=num_processors)
        self.journal_writers = journal_writer
        self.output_writer = output_writer
        self.print_reporter = PrintMessageReporter()
        self.processes = []

    def submit_job(
        self,
        target: Callable[[JournalWriter, PrintMessageReporter, OutputWriter, Any], Any],
        *args
    ):
        self.journal_writers: JournalWriter
        proc = self.executor.submit(
            target,
            self.journal_writers,
            self.print_reporter,
            self.output_writer,
            *args,
        )
        self.processes.append(proc)

    def wait_print_complete(self):
        try:
            while any([p.running() for p in self.processes]):
                key = self.print_reporter.message.keys()
                if key:
                    print(
                        "PROGRESS [{}/{} | {}]".format(
                            self.journal_writers.stats["completed"],
                            len(self.processes),
                            self.journal_writers.stats["failed"],
                        )
                    )
                    for ident in key:
                        print(self.print_reporter.message[ident], end="\n")

                    print("\n\n")
                    wait(self.processes, timeout=0.5, return_when=ALL_COMPLETED)
                    os.system("cls" if os.name == "nt" else "clear")
        except Exception as e:
            print(e)

    def reset_terminal(self):
        if os.name != "nt":
            os.system("reset")
