import sys
import os

from argparse import ArgumentParser

# Relative import fixes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openDAM.model.pun_dam_model import PUN_DAM
from openDAM.model.dam import *
from openDAM.dataio import dam_db_loader
from openDAM.dataio import dam_results_csv


def run(path, database, case_list, log_level, pun_strategy):
    """
    Run a series of cases

    :param path: path to the database file.
    :param database: database file.
    :param case_list: list of day ids to run, empty if all must be run
    :param log_level: textual log level.
    :param pun_strategy: Defines the solution strategy used when there is PUN
    """

    # Logging config
    num_log_level = getattr(logging, log_level, None)
    if not isinstance(num_log_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logging.basicConfig(level=num_log_level)  # format='%(asctime)s %(message)s'
    VERBOSE = num_log_level <= logging.DEBUG

    loader = dam_db_loader.Loader(path, database)
    cases = case_list if case_list else loader.get_all_days()
    writer = dam_results_csv.CSV_writer(path)

    # Run
    for case in cases:
        dam = loader.read_day(case)
        dam.create_model()
        try:
            if isinstance(dam, PUN_DAM):
                try:
                    options.SOLVER.options["simplex tolerances optimality"] = 1e-9
                    options.SOLVER.options["simplex tolerances feasibility"] = 1e-9
                    dam.solve(VERBOSE=True, strategy=pun_strategy)
                except:
                    print("Could not solve %d, loosening tolerances" % case)
                    options.SOLVER.options["simplex tolerances optimality"] = 1e-6
                    options.SOLVER.options["simplex tolerances feasibility"] = 1e-6
                    dam.solve(VERBOSE=True, strategy=pun_strategy)
                writer.update(dam)
            else:
                dam.create_model()
                dam.solve(VERBOSE=VERBOSE)
                if options.PRIMAL and options.DUAL:
                    writer.update(dam)
        except:
            print("Could not solve %d" % case)

        writer.close_files()


if __name__ == "__main__":
    parser = ArgumentParser(description='Day-ahead electricity market clearing algorithm')
    parser.add_argument("-p", "--path", help="Folder where data is located", default='data')
    parser.add_argument("-d", "--database",
                        help="Name of the sqlite database file, under the folder of the --path argument.",
                        default='tests.sqlite3')
    casesParser = parser.add_mutually_exclusive_group(required=True)
    casesParser.add_argument("-c", "--case", type=int, help="Case to run.")
    casesParser.add_argument("--all", help="Run all cases.", action="store_true")
    parser.add_argument("--log_dir", help="Path of the directory where debug logs are stored.",
                        default='../debug')
    parser.add_argument("--log", help="Print more details.", default='INFO')
    parser.add_argument("--pun_strategy", help="How to solve the ", default='Advanced',
                        choices=['Simple', 'NEOS', 'Advanced'])
    args = parser.parse_args()

    run(args.path, args.database, [args.case] if not args.all else [], args.log.upper(), args.pun_strategy)
