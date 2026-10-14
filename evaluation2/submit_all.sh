#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 evaluation2/generate_inputs.py
python3 - <<'PY'
import json
import subprocess
from pathlib import Path
base = Path('evaluation2')
manifest = json.loads((base / 'manifest.json').read_text())
for item in manifest:
    job_id = subprocess.check_output([
        'sbatch', '--parsable', 'evaluation2/scripts/run_case.sbatch',
        item['iteration'], item['case'], str(base / item['input_file'])
    ], universal_newlines=True).strip().split(';')[0]
    item['slurm_job_id'] = job_id
    print(f"Submitted {item['iteration']}/{item['case']}: {job_id}")
(base / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
