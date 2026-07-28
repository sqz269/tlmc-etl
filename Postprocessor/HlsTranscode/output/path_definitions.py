# Three of these names were defined twice, the .json spellings first and the
# .txt ones below. Python keeps the last binding, so the first set was dead --
# but it read as though the journals were JSON, which they are not: they are
# line-oriented text appended to by many workers.
HLS_TRANSCODE_FILELIST_OUTPUT_NAME = "hls_transcode.worklist.output.json"
HLS_TRANSCODE_FILELIST_EXPERIMENT_FS_SCAN_OUTPUT_NAME = (
    "hls_transcode.worklist.experiment.fs_scan.output.json"
)

HLS_TRANSCODE_COMPLETED_OUTPUT_NAME = "hls_transcode.completed.output.txt"

HLS_TRANSCODE_JOURNAL_COMPLETED_OUTPUT_NAME = (
    "hls_transcode.journal.completed.output.txt"
)
HLS_TRANSCODE_JOURNAL_FAILED_OUTPUT_NAME = "hls_transcode.journal.failed.output.txt"
HLS_TRANSCODE_JOURNAL_GENERAL_OUTPUT_NAME = "hls_transcode.journal.general.output.txt"


HLS_FINALIZED_FILELIST_OUTPUT_NAME = "hls.finalized.output.json"
