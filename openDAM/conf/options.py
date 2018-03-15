from pyomo.opt import SolverFactory

## Verbose mode.
VERBOSE = True

## It accounts for market split
#  in creating ATM constraints
SPLIT = True

## additional set of options
#  useful for blocks
SECONDARY_SET = True

## exponent in the binary espansion
BINARY_EXP_NUMBER = 19

## Debug mode.
DEBUG = True
LOG_FOLDER = '../debug'

## Solver.
SOLVER_NAME = 'cplex'

SOLVER = SolverFactory(SOLVER_NAME)
if SOLVER_NAME == 'cplex':
    # Local Cplex. Options in interactive format.
    SOLVER.options["timelimit"] = 1500
    SOLVER.options["mip tolerances mipgap"] = 1e-6
    SOLVER.options["emphasis mip"] = 1

    SOLVER.options["mip tolerances integrality"] = 0
    SOLVER.options["simplex tolerances optimality"] = 1e-9
    SOLVER.options["simplex tolerances feasibility"] = 1e-9

    SOLVER.options["mip strategy startalgorithm"] = 1
    SOLVER.options["mip cuts mircut"] = 2
    SOLVER.options["mip cuts flowcovers"] = 2

    if SECONDARY_SET:
        SOLVER.options["simplex crash"] = 0
        SOLVER.options["lpmethod"] = 1
        SOLVER.options["mip cuts cliques"] = 3

        # SOLVER.options["simplex pgradient"] = -1
        # SOLVER.options["mip strategy branch"] = -1
        # SOLVER.options["mip strategy variableselect"] = -1

if SOLVER is None:
    raise Exception('Unable to instanciate the solver.')

## Numerical accuracy.
EPS = 1e-4

# Network
NO_EXCHANGE_CAPACITY = False

## options for PUN_DAM
PUN_IMBALACE_TOL_LB = -1
PUN_IMBALACE_TOL_UB = 5

## options for COMPLEX_DAM

# General
PRIMAL = True
DUAL = True

# Specific to complex
APPLY_LOAD_GRADIENT = True
APPLY_SCHEDULED_STOP = True
APPLY_MIC = True and PRIMAL and DUAL
