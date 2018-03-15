from openDAM.model.dam import DAM

from pyomo.core.base import Constraint, summation, Objective, minimize, ConstraintList, \
    ConcreteModel, Set, RangeSet, Reals, Binary, NonNegativeReals, Var, maximize, Suffix
from pyomo.core.kernel import value # Looks like value method changed location in new pyomo version ?
from pyomo.environ import *  # Must be kept
from pyomo.opt import ProblemFormat, SolverStatus, TerminationCondition

import openDAM.conf.options as options

import logging

class COMPLEX_DAM(DAM):

    def __init__(self, day, zones, curves, blockOrders, complexOrders, connections=None, priceCap=(0, 3000)):
        DAM.__init__(self, day, zones, curves, blockOrders, connections, priceCap)

        self.complexOrders = complexOrders  #: a list of complex orders

        self.complex_single_orders = []  # ids of step bids belonging to complex orders

        self.create_order_book()

    def create_order_book(self):
        DAM.create_order_book(self)

        for co in self.complexOrders:
            ids = self.submit(co)
            co.set_ids(ids)

    def create_model(self):
        """
        Create and return the mathematical model.
        """

        if options.DEBUG:
            logging.info("Creating model for day %d" % self.day_id)

        # Obtain the orders book
        book = self.orders
        complexOrders = self.complexOrders

        # Create the optimization model
        model = ConcreteModel()
        model.periods = Set(initialize=book.periods)
        maxPeriod = max(book.periods)
        model.bids = Set(initialize=range(len(book.bids)))
        model.L = Set(initialize=book.locations)
        model.sBids = Set(
            initialize=[i for i in range(len(book.bids)) if book.bids[i].type == 'SB'])
        model.bBids = Set(
            initialize=[i for i in range(len(book.bids)) if book.bids[i].type == 'BB'])
        model.cBids = RangeSet(len(complexOrders))  # Complex orders
        model.C = RangeSet(len(self.connections))
        model.directions = RangeSet(2)  # 1 == up, 2 = down TODO: clean

        # Variables
        model.xs = Var(model.sBids, domain=Reals,
                       bounds=(0.0, 1.0))  # Single period bids acceptance
        model.xb = Var(model.bBids, domain=Binary)  # Block bids acceptance
        model.xc = Var(model.cBids, domain=Binary)  # Complex orders acceptance
        model.pi = Var(model.L * model.periods, domain=Reals, bounds=self.priceCap)  # Market prices
        model.s = Var(model.bids, domain=NonNegativeReals)  # Bids
        model.sc = Var(model.cBids, domain=NonNegativeReals)  # complex orders
        model.complexVolume = Var(model.cBids, model.periods, domain=Reals)  # Bids
        model.pi_lg_up = Var(model.cBids * model.periods, domain=NonNegativeReals)  # Market prices
        model.pi_lg_down = Var(model.cBids * model.periods,
                               domain=NonNegativeReals)  # Market prices
        model.pi_lg = Var(model.cBids * model.periods, domain=Reals)  # Market prices

        def flowBounds(m, c, d, t):
            capacity = self.connections[c - 1].capacity_up[t] if d == 1 else \
                self.connections[c - 1].capacity_down[t]
            return (0, capacity)

        model.f = Var(model.C * model.directions * model.periods, domain=NonNegativeReals,
                      bounds=flowBounds)
        model.u = Var(model.C * model.directions * model.periods, domain=NonNegativeReals)

        # Objective
        def primalObj(m):
            # Single period bids cost
            expr = summation({i: book.bids[i].price * book.bids[i].volume for i in m.sBids}, m.xs)
            # Block bids cost
            expr += summation(
                {i: book.bids[i].price * sum(book.bids[i].volumes.values()) for i in m.bBids}, m.xb)
            return -expr

        if options.PRIMAL and not options.DUAL:
            model.obj = Objective(rule=primalObj, sense=maximize)

        def primalDualObj(m):
            return primalObj(m) + sum(1e-5 * m.xc[i] for i in model.cBids)

        if options.PRIMAL and options.DUAL:
            model.obj = Objective(rule=primalDualObj, sense=maximize)

        # Complex order constraint
        if options.PRIMAL and options.DUAL:
            model.deactivate_suborders = ConstraintList()
            for o in model.cBids:
                sub_ids = complexOrders[o - 1].ids
                curves = complexOrders[o - 1].curves
                for id in sub_ids:
                    bid = book.bids[id]
                    if bid.period <= complexOrders[o - 1].SSperiods and bid.price == \
                            curves[bid.period].bids[0].price:
                        pass  # This bid, first step of the cruve in the scheduled stop periods, is not automatically deactivated when MIC constraint is not satisfied
                    else:
                        model.deactivate_suborders.add(model.xs[id] <= model.xc[o])

        # Ramping constraints for complex orders
        def complex_volume_def_rule(m, o, p):
            sub_ids = complexOrders[o - 1].ids
            return m.complexVolume[o, p] == sum(
                m.xs[i] * book.bids[i].volume for i in sub_ids if book.bids[i].period == p)

        if options.PRIMAL:
            model.complex_volume_def = Constraint(model.cBids, model.periods,
                                                  rule=complex_volume_def_rule)

        def complex_lg_down_rule(m, o, p):
            if p + 1 > maxPeriod or complexOrders[o - 1].ramp_down == None:
                return Constraint.Skip
            else:
                return m.complexVolume[o, p] - m.complexVolume[o, p + 1] <= complexOrders[
                                                                                o - 1].ramp_down * \
                                                                            m.xc[o]

        if options.PRIMAL and options.APPLY_LOAD_GRADIENT:
            model.complex_lg_down = Constraint(model.cBids, model.periods,
                                               rule=complex_lg_down_rule)

        def complex_lg_up_rule(m, o, p):
            if p + 1 > maxPeriod or complexOrders[o - 1].ramp_up == None:
                return Constraint.Skip
            else:
                return m.complexVolume[o, p + 1] - m.complexVolume[o, p] <= complexOrders[
                    o - 1].ramp_up

        if options.PRIMAL and options.APPLY_LOAD_GRADIENT:
            model.complex_lg_up = Constraint(model.cBids, model.periods,
                                             rule=complex_lg_up_rule)  # Balance constraint

        # Energy balance constraints
        balanceExpr = {l: {t: 0.0 for t in model.periods} for l in model.L}
        for i in model.sBids:  # Simple bids
            bid = book.bids[i]
            balanceExpr[bid.location][bid.period] += bid.volume * model.xs[i]
        for i in model.bBids:  # Block bids
            bid = book.bids[i]
            for t, v in bid.volumes.items():
                balanceExpr[bid.location][t] += v * model.xb[i]

        def balanceCstr(m, l, t):
            export = 0.0
            for c in model.C:
                if self.connections[c - 1].from_id == l:
                    export += m.f[c, 1, t] - m.f[c, 2, t]
                elif self.connections[c - 1].to_id == l:
                    export += m.f[c, 2, t] - m.f[c, 1, t]
            return balanceExpr[l][t] == export

        if options.PRIMAL:
            model.balance = Constraint(model.L * book.periods, rule=balanceCstr)

        # Surplus of single period bids
        def sBidSurplus(m, i):  # For the "usual" step orders
            bid = book.bids[i]
            if i in self.plain_single_orders:
                return m.s[i] >= (m.pi[bid.location, bid.period] - bid.price) * bid.volume
            else:
                return Constraint.Skip

        if options.DUAL:
            model.sBidSurplus = Constraint(model.sBids, rule=sBidSurplus)

        # Surplus definition for complex suborders accounting for impact of load gradient condition
        if options.DUAL:
            model.complex_sBidSurplus = ConstraintList()
            for o in model.cBids:
                sub_ids = complexOrders[o - 1].ids
                l = complexOrders[o - 1].location
                for i in sub_ids:
                    bid = book.bids[i]
                    model.complex_sBidSurplus.add(model.s[i] >= (
                        model.pi[l, bid.period] + model.pi_lg[
                            o, bid.period] - bid.price) * bid.volume)

        def LG_price_def_rule(m, o, p):
            l = complexOrders[o - 1].location

            exp = 0
            if options.APPLY_LOAD_GRADIENT:
                D = complexOrders[o - 1].ramp_down
                U = complexOrders[o - 1].ramp_up
                if D is not None:
                    exp += (m.pi_lg_down[o, p - 1] if p > 1 else 0) - (
                        m.pi_lg_down[o, p] if p < maxPeriod else 0)
                if U is not None:
                    exp -= (m.pi_lg_up[o, p - 1] if p > 1 else 0) - (
                        m.pi_lg_up[o, p] if p < maxPeriod else 0)

            return m.pi_lg[o, p] == exp

        if options.DUAL:
            model.LG_price_def = Constraint(model.cBids, model.periods, rule=LG_price_def_rule)

        # Surplus of block bids
        def bBidSurplus(m, i):
            bid = book.bids[i]
            bidVolume = -sum(bid.volumes.values())
            bigM = (self.priceCap[1] - self.priceCap[0]) * bidVolume  # FIXME tighten BIGM
            return m.s[i] + sum([m.pi[bid.location, t] * -v for t, v in
                                 bid.volumes.items()]) >= bid.cost * bidVolume + bigM * (
                1 - m.xb[i])

        if options.DUAL:
            model.bBidSurplus = Constraint(model.bBids, rule=bBidSurplus)

        # Surplus of complex orders
        def cBidSurplus(m, o):
            complexOrder = complexOrders[o - 1]
            sub_ids = complexOrder.ids
            if book.bids[sub_ids[0]].volume > 0:  # supply
                bigM = sum(
                    (self.priceCap[1] - book.bids[i].price) * book.bids[i].volume for i in sub_ids)
            else:
                bigM = sum(
                    (book.bids[i].price - self.priceCap[0]) * book.bids[i].volume for i in sub_ids)
            return m.sc[o] + bigM * (1 - m.xc[o]) >= sum(m.s[i] for i in sub_ids)

        if options.DUAL:
            model.cBidSurplus = Constraint(model.cBids, rule=cBidSurplus)

        # Surplus of complex orders
        def cBidSurplus_2(m, o):
            complexOrder = complexOrders[o - 1]
            expr = 0
            for i in complexOrder.ids:
                bid = book.bids[i]
                if (bid.period <= complexOrder.SSperiods) and (
                            bid.price == complexOrder.curves[bid.period].bids[0].price):
                    expr += m.s[i]
            return m.sc[o] >= expr

        if options.DUAL:
            model.cBidSurplus_2 = Constraint(model.cBids, rule=cBidSurplus_2)  # MIC constraint

        def cMIC(m, o):
            complexOrder = complexOrders[o - 1]

            if complexOrder.FT == 0 and complexOrder.VT == 0:
                return Constraint.Skip

            expr = 0
            bigM = complexOrder.FT
            for i in complexOrder.ids:
                bid = book.bids[i]
                if (bid.period <= complexOrder.SSperiods) and (
                            bid.price == complexOrder.curves[bid.period].bids[0].price):
                    bigM += (
                        bid.volume * (
                            self.priceCap[1] - bid.price))  # FIXME assumes order is supply
                expr += bid.volume * m.xs[i] * (bid.price - complexOrder.VT)

            return m.sc[o] + expr + bigM * (1 - m.xc[o]) >= complexOrder.FT

        if options.DUAL and options.PRIMAL:
            model.cMIC = Constraint(model.cBids, rule=cMIC)

        # Dual connections capacity
        def dualCapacity(m, c, t):
            exportPrices = 0.0
            for l in m.L:
                if l == self.connections[c - 1].from_id:
                    exportPrices += m.pi[l, t]
                elif l == self.connections[c - 1].to_id:
                    exportPrices -= m.pi[l, t]
            return m.u[c, 1, t] - m.u[c, 2, t] + exportPrices == 0.0

        if options.DUAL:
            model.dualCapacity = Constraint(model.C * model.periods, rule=dualCapacity)

        # Dual optimality
        def dualObj(m):
            dualObj = summation(m.s) + summation(m.sc)

            for o in m.cBids:
                sub_ids = complexOrders[o - 1].ids
                for id in sub_ids:
                    dualObj -= m.s[
                        id]  # Remove contribution of complex suborders which were accounted for in prevous summation over single bids

                if options.APPLY_LOAD_GRADIENT:
                    ramp_down = complexOrders[o - 1].ramp_down
                    ramp_up = complexOrders[o - 1].ramp_up
                    for p in m.periods:
                        if p == maxPeriod:
                            continue
                        if ramp_down is not None:
                            dualObj += ramp_down * m.pi_lg_down[
                                o, p]  # Add contribution of load gradient
                        if ramp_up is not None:
                            dualObj += ramp_up * m.pi_lg_up[
                                o, p]  # Add contribution of load gradient

            for c in model.C:
                for t in m.periods:
                    dualObj += self.connections[c - 1].capacity_up[t] * m.u[c, 1, t]
                    dualObj += self.connections[c - 1].capacity_down[t] * m.u[c, 2, t]

            return dualObj

        if not options.PRIMAL:
            model.obj = Objective(rule=dualObj, sense=minimize)

        def primalEqualsDual(m):
            return primalObj(m) >= dualObj(m)

        if options.DUAL and options.PRIMAL:
            model.primalEqualsDual = Constraint(rule=primalEqualsDual)

        self.model = model

    def solve(self, VERBOSE=False, cutoff=-1.0, fixedComplexOrders=None):
        """
        Solve the problem

        :param cutoff: cutoff passed to the solver, hence solver will cut branches where objective is worse than this value.
        :param fixedComplexOrders: dictionnary with complexOrders as keys and a value to be fixed.
        """
        if fixedComplexOrders is None:
            fixedComplexOrders = {}

        logging.info('Solving day %d' % self.day_id)

        if options.SOLVER_NAME == 'gurobi':
            options.SOLVER.options['cutoff'] = cutoff
        elif cutoff > -1.0:
            logging.warn("Specifying a cutoff value is implemented for Gurobi only.")
        # FIXME This should be generalized for other solvers, should probably create a clean mapping of the main parameters for the different solvers in another place.

        if options.APPLY_MIC:
            for i in self.model.cBids:
                if i in fixedComplexOrders.keys():
                    self.model.xc[i] = fixedComplexOrders[i]
                    self.model.xc[i].fixed = True
                else:
                    self.model.xc[i].setlb(0)
                    self.model.xc[i].setub(1)
                    self.model.xc[i].fixed = False
        else:
            for o in self.model.cBids:  # We can fix all MIC related variables
                self.model.xc[o] = 1
                self.model.xc[o].fixed = True

        # Solve
        options.SOLVER.solve(self.model, tee=VERBOSE)
        if len(self.model.solutions) == 0:
            self.exportModel()
            raise Exception('No solution found when clearing the day-ahead energy market.')

        # Load results
        if options.PRIMAL and options.DUAL:
            self._build_solution()
            self._checkSolution()

    def _build_solution(self, results=None):
        """
        Store the solution of the day-ahead market in the order book.
        """
        model = self.model
        book = self.orders
        complexOrders = self.complexOrders

        book.volumes = {s: {l: {t: 0.0 for t in book.periods} for l in model.L} for s in
                        ['SUPPLY', 'DEMAND']}
        book.prices = {l: {t: model.pi[l, t].value for t in book.periods} for l in model.L}

        self.welfare = value(model.obj)
        logging.info("welfare: %.2f" % value(self.welfare))

        for i in model.sBids:
            bid = book.bids[i]

            # Obtain and save the volume
            xs = model.xs[i].value
            bid.acceptance = xs

            # Update volumes and prices
            if xs > options.EPS:
                # Compute the total volumes exchanged
                supplydemand = "SUPPLY" if bid.volume > 0 else "DEMAND"
                t = bid.period
                book.volumes[supplydemand][bid.location][t] += bid.volume * xs

        for c in model.C:
            flow_up = []
            flow_down = []
            congestion_up = []
            congestion_down = []
            for p in model.periods:
                flow_up.append(model.f[c, 1, p].value)
                flow_down.append(model.f[c, 2, p].value)
                congestion_up.append(model.u[c, 1, p].value)
                congestion_down.append(model.u[c, 2, p].value)
            self.connections[c - 1].flow_up = flow_up
            self.connections[c - 1].flow_down = flow_down
            self.connections[c - 1].congestion_up = congestion_up
            self.connections[c - 1].congestion_down = congestion_down

        for i in model.bBids:
            bid = book.bids[i]

            # Obtain and save the volume
            xb = model.xb[i].value
            bid.acceptance = model.xb[i].value

            if xb > options.EPS:
                supplydemand = "SUPPLY" if bid.volumes[0] > 0 else "DEMAND"
                for t, v in bid.volumes.items():
                    book.volumes[bid.location][t] += v

        for i in model.cBids:
            # logging.info('building solution for complex %d' % i)
            bid = complexOrders[i - 1]

            # Obtain and save the volume
            bid.acceptance = model.xc[i].value
            bid.surplus = model.sc[i].value
            bid.volumes = [model.complexVolume[i, p].value for p in model.periods]
            bid.pi_lg = [model.pi[bid.location, p].value for p in
                         model.periods]  # FIXME could be removed

            if bid.acceptance < options.EPS:  # Bid is rejected, is it paradoxically ?
                bid.tentativeVolumes = dict(zip(model.periods, [0.0] * len(model.periods)))
                for p in model.periods:
                    for i in bid.ids:
                        if book.bids[i].price <= bid.pi_lg[p - 1]:  # FIXME assuming supply
                            bid.tentativeVolumes[p] += book.bids[i].volume
                bid.tentativeIncome = sum(
                    bid.tentativeVolumes[p] * bid.pi_lg[p - 1] for p in model.periods)
                bid.isPR = (bid.tentativeIncome >= bid.FT + bid.VT * sum(
                    bid.tentativeVolumes[p] for p in model.periods))
            else:
                bid.tentativeVolumes = {}
                bid.tentativeIncome = 0
                bid.isPR = False

    def getPRcomplexOrders(self, complexOrders, VERBOSE=True):
        """
        Paradoxically rejected orders.

        :param complexOrders: the list of complex orders you are interested in knowing the status.
        :param VERBOSE: print the list.
        :return: a sublist of the input list of complex orders, sorted by increasing VT.
        """
        PRcomplexOrders = sorted([c for c in complexOrders if c.isPR], key=lambda c: c.VT)

        if VERBOSE:
            logging.debug("Paradoxically rejected complex orders:")
            for c in PRcomplexOrders:
                logging.debug(c.complex_id, c.FT, c.VT, c.tentativeIncome, c.tentativeVolumes)

        return PRcomplexOrders

    def _checkSolution(self):
        """
        Perform some checks on the solution to ensure it is OK.
        """
        model = self.model
        book = self.orders
        complexOrders = self.complexOrders

        slack_sBids = []
        for i in model.sBids:
            if i in self.plain_single_orders:
                slack_sBids.append(model.s[i].value * (1 - model.xs[i].value))
        if len(slack_sBids) > 0 and abs(max(slack_sBids)) > 1e-5:
            print("max slack sBids = %f" % max(slack_sBids))

        slack_bBids = []
        for i in model.bBids:
            slack_bBids.append(model.s[i].value * (1 - model.xb[i].value))
        if len(slack_bBids) > 0 and abs(max(slack_bBids)) > 1e-5:
            print("max slack bBids = %f" % max(slack_bBids))

        slack_complex = []
        for o in model.cBids:
            slack_sBids = []
            for i in complexOrders[o - 1].ids:
                slack_sBids.append(model.s[i].value * (model.xc[o].value - model.xs[i].value))
            if len(slack_sBids) > 0 and abs(max(slack_sBids)) > 1e-5:
                print("max slack hourlyBids for complex %d = %f" % (o, max(slack_sBids)))

            slack_complex.append(model.sc[o].value * (1 - model.xc[o].value))
        if len(slack_complex) > 0 and abs(max(slack_complex)) > 1e-5:
            logging.debug("slack complex orders = %s" % dict(zip(model.cBids, slack_complex)))