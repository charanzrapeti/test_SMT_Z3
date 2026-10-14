#!/usr/bin/env bash
#SBATCH --job-name=eval2-smt
#SBATCH --account=uni-siegen
#SBATCH --partition=long
#SBATCH --time=5-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --output=evaluation2/%x-%j.out
#SBATCH --error=evaluation2/%x-%j.err
set -euo pipefail
module load python/3.14.3
echo "[EVAL2] Python: $(python3 --version)"
if [[ $# -ne 3 ]]; then echo "Usage: sbatch run_case.sbatch ITERATION CASE INPUT" >&2; exit 2; fi
iteration=$1
case_name=$2
input=$3
base="evaluation2/${iteration}"
mkdir -p "$base/output" "$base/logs"
echo "[EVAL2] case=$case_name input=$input iteration=$iteration job_id=${SLURM_JOB_ID:-unknown}"
python3 -u solver.py "$input" --output-file "$base/output/${case_name}_binary_search.json" --log 2>&1 | tee "$base/logs/${case_name}_binary_search.log"
python3 -u solver2.py "$input" --output-file "$base/output/${case_name}_z3_makespan.json" --log 2>&1 | tee "$base/logs/${case_name}_z3_makespan.log"
echo "[EVAL2] case=$case_name completed"
