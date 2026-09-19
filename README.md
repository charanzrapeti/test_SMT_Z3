# SMT-Based Scheduler for Distributed Time-Sensitive Networks

This code is an SMT-based scheduler designed for distributed time-sensitive networks.

## File Structure

- `input/`: Contains the application and network topology input files (in `.json` format).
- `misc/`: Contains older versions of schedulers and scripts that are not currently in use.
- `output/`: The destination folder for scheduled output files.
  - Naming convention: If `input_file` is `input/graph_3.json`, the output file will be `output/graph_3_smt_output.json`.
- `prevSchedules/`: Contains schedules generated using older versions of the scheduler.
- `util/`: Contains helper files imported by the main script:
  - `compute_min.py`: Computes the minimum time of the longest chain in the DAG of the input file.
  - `KPathFinding.py`: Used to find K paths between nodes (returns cost array).
  - `KPathFinding2.py`: Used to find K paths between nodes (returns both cost and paths array). This is the version currently used in the main script.
- `__pycache__/`: Compiled Python files.
- `README.md`: This file.
- `schedule_output_paper_model.json`: Pre-computed schedule output.
- `test2 copy.py`: Older or alternative script version.
- `test2Parallize.py`: The main scheduler script.

## How to Run the Script

### Option 1: Using Existing Input Files
You can run the scheduler using existing files located in the `input/` folder (e.g., `graph_0.json`, `graph_1.json`).
1. Run `test2Parallize.py`. By default, it runs on `graph_0.json`.
2. To run on a different file, modify the input file name directly within the `test2Parallize.py` script.
   - *Note: You may need to manually add a "deadline" property to the application JSON if missing.*

### Option 2: Creating Your Own Input Files
To generate new input files, follow these steps:

1. **Generate TGFF files**:
   - Use TGFF on Ubuntu to generate files.
   - Create a `.tgffopt` file (e.g., `simple.tgffopt`) and run it using the command:
     `/tgff examples/simple` (do not include the extension).
   - This generates a `simple.tgff` file in the examples folder.

2. **Process TGFF files**:
   - Use the `parsetgff.py` script, passing the generated `.tgff` file as an argument.
   - This script extracts the data and saves the resulting JSON files into the `input/` folder.
   - *Note: The python script uses a hardcoded platform model for all files, as TGFF only generates the application model. You must manually add the "deadline" field to the generated JSON files if required.*

3. **Run the Scheduler**:
   - Once the files are in the `input/` folder, follow the steps provided in **Option 1**.


   ** Tests ** : 
   - Baseline result: the current scheduler reaches 38 independent jobs in under 5 minutes, then times out at 41. With messages added after that, 38 tasks/9 messages still schedules
