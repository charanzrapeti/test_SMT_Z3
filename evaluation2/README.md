# Evaluation 2

`submit_all.sh` generates 45 reproducible benchmark cases and submits one five-day Slurm job per case. Each job runs `solver.py --log` (binary-search feasibility) and `solver2.py --log` (a single Z3 `Optimize` makespan solve). Inputs and outputs are isolated by iteration.

The iteration sizes are 10, 20, 10, and 5 cases for task ranges 50–80, 82–120, 128–200, and 210–250. Names use `<tasks>T_<messages>M.json`; messages are at least the task count, with 0, 10, or 20 extra messages.

Generation uses `util/inputFileGenerator.py` functions and `util/simple6.tgff` graph 2. The generator records the uniform WCET offset used to keep `l_min` strictly increasing in `manifest.json`.

After completion, run `python3 evaluation2/logs/plot_results.py` to create `results.csv` and comparison graphs. Binary-search logs retain per-iteration SMT counts and timing.
