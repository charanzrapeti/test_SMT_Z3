#!/usr/bin/env bash
# Run one missing Evaluation 2 result with scheduler logs kept per iteration.
# Usage: sbatch run_missing_case.sbatch ITERATION CASE SOLVER
# SOLVER is binary_search or z3_makespan.
#SBATCH --account=uni-siegen
#SBATCH --partition=long
#SBATCH --time=14-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --output=evaluation2/%x-%j.out
#SBATCH --error=evaluation2/%x-%j.err
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: sbatch run_missing_case.sbatch ITERATION CASE SOLVER" >&2
    exit 2
fi

iteration=$1
case_name=$2
solver_kind=$3
case "$iteration" in
    iteration3|iteration4) ;;
    *) echo "Unsupported iteration: $iteration" >&2; exit 2 ;;
esac
case "$solver_kind" in
    binary_search) solver_script=solver.py ;;
    z3_makespan) solver_script=solver2.py ;;
    *) echo "Unsupported solver: $solver_kind" >&2; exit 2 ;;
esac

base="evaluation2/${iteration}"
input="$base/input/${case_name}.json"
output="$base/output/${case_name}_${solver_kind}.json"
log="$base/logs/${case_name}_${solver_kind}.log"
if [[ ! -f "$input" ]]; then echo "Missing input: $input" >&2; exit 2; fi
mkdir -p "$base/output" "$base/logs" "$base/pendinglogs"

module load python/3.14.3
echo "[EVAL2] case=$case_name solver=$solver_kind input=$input job_id=${SLURM_JOB_ID:-unknown}"
if [[ "$solver_kind" == binary_search ]]; then
    python3 -u "$solver_script" "$input" --output-file "$output" --log 2>&1 | tee "$log"
else
    python3 -u "$solver_script" "$input" --output-file "$output" --log 2>&1 | tee "$log"
fi
echo "[EVAL2] case=$case_name solver=$solver_kind completed"
