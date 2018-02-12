from pyomo.opt import SolverFactory

## Verbose mode.
VERBOSE = True

## Debug mode.
DEBUG = True
LOG_FOLDER = '../debug'

## Solver.
SOLVER_NAME = 'cplex'

SOLVER = SolverFactory(SOLVER_NAME)
if SOLVER_NAME == 'cplex':
    # Local Cplex. Options in interactive format.
    SOLVER.options["timelimit"] = 600
    SOLVER.options["mip tolerances mipgap"] = 1e-4
    SOLVER.options["emphasis mip"] = 1

    SOLVER.options["mip tolerances integrality"] = 0
    SOLVER.options["simplex tolerances optimality"] = 1e-9
    SOLVER.options["simplex tolerances feasibility"] = 1e-9
    SOLVER.options["simplex pgradient"] = -1
    SOLVER.options["simplex crash"] = 0

    SOLVER.options["mip strategy startalgorithm"] = 1
    SOLVER.options["mip strategy branch"] = -1
    SOLVER.options["mip strategy variableselect"] = -1

    SOLVER.options["mip cuts mircut"] = 2
    SOLVER.options["mip cuts flowcovers"] = 2

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
