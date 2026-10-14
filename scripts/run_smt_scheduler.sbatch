#!/usr/bin/env bash
# One Slurm allocation runs exactly one SMT input file.
# Submit through scripts/submit_newpm_jobs.sh rather than invoking this file directly.
#
# Use the scheduler's default of one SMT worker.
# Change these #SBATCH values if your allocation policy requires different limits.
#SBATCH --job-name=smt-scheduler
#SBATCH --account=uni-siegen
#SBATCH --partition=long
#SBATCH --time=15-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --output=logs/slurm/%x-%j.out
#SBATCH --error=logs/slurm/%x-%j.err

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: sbatch $0 INPUT_JSON OUTPUT_JSON" >&2
    exit 2
fi

input_file=$1
output_file=$2

mkdir -p "$(dirname "$output_file")"

echo "Started: $(date --iso-8601=seconds)"
echo "Host: $(hostname)"
echo "Job ID: ${SLURM_JOB_ID:-unknown}"
echo "Input: ${input_file}"
echo "Schedule output: ${output_file}"
echo "CPUs allocated: ${SLURM_CPUS_PER_TASK:-1}; SMT workers: default (1)"

# -u makes Python flush --log output promptly, so tail can show live progress.
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-1}" \
    python3 -u solver.py "$input_file" \
        --output-file "$output_file" \
        --log

echo "Finished: $(date --iso-8601=seconds)"
