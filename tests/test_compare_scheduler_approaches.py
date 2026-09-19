import subprocess
import sys
from pathlib import Path

from scripts.compare_scheduler_approaches import run_scheduler


def test_run_scheduler_times_out_cleanly(tmp_path):
    script = tmp_path / "slow_script.py"
    script.write_text(
        "import time\n"
        "time.sleep(5)\n"
        "print('done')\n",
        encoding="utf-8",
    )
    input_file = tmp_path / "sample.json"
    input_file.write_text('{"job": 1}', encoding="utf-8")
    output_file = tmp_path / "out.txt"

    result = run_scheduler(script, input_file, output_file, timeout_seconds=0.5)

    assert result["status"] == "failed"
    assert result["scheduler_seconds"] is None
    assert result["wall_seconds"] >= 0.4
