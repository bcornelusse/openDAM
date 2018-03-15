from openDAM.model.dam import DAM

from pyomo.core.base import Constraint, summation, Objective, minimize, ConstraintList, \
    ConcreteModel, Set, RangeSet, Reals, Binary, NonNegativeReals, Var, maximize, Suffix
from pyomo.core.kernel import value  # Looks like value method changed location in new pyomo version ?
from pyomo.environ import *  # Must be kept
from pyomo.opt import ProblemFormat, SolverStatus, TerminationCondition

import openDAM.conf.options as options

import logging

import time

import itertools


class PUN_DAM(DAM):
    def __init__(self, day, zones, curves, blockOrders, punOrders, connections=None, priceCap=(0, 3000), loader=None):
        DAM.__init__(self, day, zones, curves, blockOrders, connections, priceCap)

        self.punOrders = punOrders  #: a list of pun orders
        self.pun_orders_ids = {}  # ids of PUN orders
        self.pun_orders_by_period = None

        self.relax_PUN = False

        self.loader = loader

        self.create_order_book()

    def create_order_book(self):
        DAM.create_order_book(self)

        for po in self.punOrders:
            self.submit(po)

    def create_model(self, relax_PUN=False, ESTIMATED_PUN_PRICES_RANGES=None):
        """
        Model based on Iacopo Savelli's research.

        Names are normally coherent with names in the latex documentation (macros)

        :return: A pyomo model to be solved.
        """

        self.relax_PUN = relax_PUN

        if ESTIMATED_PUN_PRICES_RANGES:
            assert (not self.relax_PUN)

        if options.DEBUG:
            logging.info("Creating PUN model for day %d" % self.day_id)

        # Obtain the orders book
        book = self.orders
        pun_orders = self.punOrders

        # Convenience data structures
        self.pun_orders_by_period = dict(zip(book.periods, [[] for p in book.periods]))
        pun_zones = set()
        for po in pun_orders:
            self.pun_orders_by_period[po.period].append(po)
            pun_zones.add(po.location)

        # Create the optimization model
        model = ConcreteModel(name="DAM with PUN")

        # Sets
        model.periods = Set(initialize=book.periods)
        maxPeriod = max(book.periods)
        model.bids = Set(initialize=range(len(book.bids)))
        model.L = Set(initialize=self.zones.keys())
        model.Lpun = Set(initialize=pun_zones)
        model.LpunExt = Set(initialize=[z for z in self.zones if z in pun_zones or self.zones[z].name == "ROSN"])
        model.demandBids = Set(
            initialize=[i for i in range(len(book.bids)) if
                        (book.bids[i].type == 'SB' and book.bids[i].volume < 0)])
        model.supplyBids = Set(
            initialize=[i for i in range(len(book.bids)) if
                        (book.bids[i].type == 'SB' and book.bids[i].volume > 0)])
        model.bBids = Set(
            initialize=[i for i in range(len(book.bids)) if book.bids[i].type == 'BB'])
        model.punBids = Set(
            initialize=[i for i in range(len(book.bids)) if book.bids[i].type == 'PO'])
        model.C = RangeSet(len(self.connections))
        model.binary_powers = Set(initialize=range(options.BINARY_EXP_NUMBER))

        # Number of binary variables. Must be decreased if the binary is fixed.
        # ugk, uek, uwd, udd = 4*len(model.punBids)
        # bexp = len(model.Lpun)*len(model.binary_powers)*len(model.periods)
        # uf = len(model.LpunExt)*len(model.LpunExt)*len(model.periods)
        # ubp = len(model.bBids)
        self.nbinvar = 4 * len(model.punBids) \
                       + len(model.Lpun) * len(model.binary_powers) * len(model.periods) \
                       + len(model.bBids)
        if options.SPLIT:
            self.nbinvar += len(model.LpunExt) * len(model.LpunExt) * len(model.periods)

        self.nbinvar_initial = self.nbinvar

        # Big Ms
        MAX_PRICE = self.priceCap[1]
        MIN_PRICE = self.priceCap[0]
        PUN_EPSILON = 1e-8
        UF_EPSILON = 1e-6
        M_pun_itm = MAX_PRICE + 1
        M_pun_atm = MAX_PRICE  # TODO ensure right value
        M_pun_itm_objective = MAX_PRICE
        M_ugtk_pun_upper = MAX_PRICE
        M_ugtk_non_pun_upper = MAX_PRICE
        M_uwtk_lower = MIN_PRICE
        M_uwtk_upper = MAX_PRICE
        M_ugtk_pun_lower = MIN_PRICE
        M_ugtk_non_pun_lower = MIN_PRICE
        M_udtk_lower = MIN_PRICE
        M_udtk_upper = MAX_PRICE
        M_block_surplus = MAX_PRICE - MIN_PRICE

        if options.DEBUG:
            logging.info("Defining variables")
        # Variables # TODO blocks
        model.dk = Var(model.demandBids, domain=NonNegativeReals)
        model.sp = Var(model.supplyBids, domain=NonNegativeReals)
        model.rp = Var(model.bBids, domain=NonNegativeReals)  # Block bids acceptance
        model.ubp = Var(model.bBids, domain=Binary)

        model.f = Var(model.L, model.L, model.periods, domain=Reals)

        model.dwk = Var(model.punBids, domain=NonNegativeReals)  # PUN
        model.vphikPUNw = Var(model.punBids, domain=NonNegativeReals)
        if relax_PUN:
            model.uwk = Var(model.punBids, domain=NonNegativeReals, bounds=(0, 1))  # PUN
        else:
            model.dkpi = Var(model.punBids, domain=NonNegativeReals)  # PUN
            model.ddk = Var(model.punBids, domain=NonNegativeReals)  # PUN
            model.bexp = Var(model.periods, model.binary_powers, model.Lpun, domain=Binary)  # PUN
            model.ugk = Var(model.punBids, domain=Binary)  # PUN
            model.uek = Var(model.punBids, domain=Binary)  # PUN
            model.uwk = Var(model.punBids, domain=Binary)  # PUN
            model.udk = Var(model.punBids, domain=Binary)  # PUN
            if options.SPLIT:
                model.uf = Var(model.LpunExt, model.LpunExt, model.periods, domain=Binary)

            # Dual
            model.pi = Var(model.periods, domain=Reals)
            model.imbalance = Var(model.periods, domain=Reals, bounds=(options.PUN_IMBALACE_TOL_LB,
                                                                       options.PUN_IMBALACE_TOL_UB))

            # Linearization related variables
            model.yugPUNk = Var(model.punBids, domain=Reals)
            model.yugPzk = Var(model.punBids, domain=Reals)
            model.yuwvphik = Var(model.punBids, domain=NonNegativeReals)
            model.ybPzi = Var(model.periods, model.binary_powers, model.Lpun, domain=Reals)

        model.pZi = Var(model.L, model.periods, domain=Reals)

        # Dual
        model.vphiknonPUNw = Var(model.demandBids, domain=NonNegativeReals)
        model.vphip = Var(model.supplyBids, domain=NonNegativeReals)
        model.deltaMax = Var(model.L, model.L, model.periods, domain=NonNegativeReals)
        model.etaij = Var(model.L, model.L, model.periods, domain=Reals)
        model.vphibMax = Var(model.bBids, domain=NonNegativeReals)
        model.vphibMin = Var(model.bBids, domain=NonNegativeReals)

        # Linearization related variables
        model.ypMax = Var(model.bBids, domain=NonNegativeReals)
        model.ypMin = Var(model.bBids, domain=NonNegativeReals)

        if options.DEBUG:
            logging.info("Calculating flow max")

        model.flow_max = {}
        for p in model.periods:
            for (local, foreign) in model.L * model.L:
                model.flow_max[local, foreign, p] = 0
                for c in model.C:
                    if self.connections[c - 1].from_id == local \
                            and self.connections[c - 1].to_id == foreign:
                        model.flow_max[local, foreign, p] = self.connections[c - 1].capacity_up[p]
                        break
                    elif self.connections[c - 1].from_id == foreign \
                            and self.connections[c - 1].to_id == local:
                        model.flow_max[local, foreign, p] = self.connections[c - 1].capacity_down[p]
                        break

        # Constraints

        if options.DEBUG:
            logging.info("Creating Block binary variables relations constraints")

        def p_block_itm_rule(m, b):
            bid = book.bids[b]
            V = bid.total_volume()
            M = M_block_surplus * V
            l = bid.location
            P = bid.price
            return sum([m.pZi[l, t] * v for t, v in bid.volumes.items()]) - P * V >= -M * (1 - m.ubp[b])

        if not relax_PUN:
            model.p_block_itm = Constraint(model.bBids, rule=p_block_itm_rule)

        if options.DEBUG:
            logging.info("Creating PUN binary variables relations constraints")

        # Upper level constraints
        def p_pun_itm_le_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return bid.price - m.pi[bid.period] <= M_pun_itm * m.ugk[b]

        if not relax_PUN:
            model.p_pun_itm_le = Constraint(model.punBids, rule=p_pun_itm_le_rule)

        def p_pun_itm_ge_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return bid.price - m.pi[bid.period] >= PUN_EPSILON - M_pun_itm * (1 - m.ugk[b])

        if not relax_PUN:
            model.p_pun_itm_ge = Constraint(model.punBids, rule=p_pun_itm_ge_rule)

        def p_pun_atm_le_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return bid.price - m.pi[bid.period] <= M_pun_atm * (1 - m.uek[b])

        if not relax_PUN:
            model.p_pun_atm_le = Constraint(model.punBids, rule=p_pun_atm_le_rule)

        def p_pun_atm_ge_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return bid.price - m.pi[bid.period] >= -M_pun_atm * (1 - m.uek[b])

        if not relax_PUN:
            model.p_pun_atm_ge = Constraint(model.punBids, rule=p_pun_atm_ge_rule)

        def p_pun_atm_welfare_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return m.uwk[b] <= m.uek[b]

        if not relax_PUN:
            model.p_pun_atm_welfare = Constraint(model.punBids, rule=p_pun_atm_welfare_rule)

        def p_pun_atm_dispatch_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return m.udk[b] <= m.uek[b]

        if not relax_PUN:
            model.p_pun_atm_dispatch = Constraint(model.punBids, rule=p_pun_atm_dispatch_rule)

        def p_pun_atm_welfare_xor_dispatch_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return m.udk[b] <= 1 - m.uwk[b]

        if not relax_PUN:
            model.p_pun_atm_welfare_xor_dispatch = Constraint(model.punBids, rule=p_pun_atm_welfare_xor_dispatch_rule)

        def p_pun_atm_quantity_dispatch_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return m.ddk[b] <= bid.volume * m.udk[b]

        if not relax_PUN:
            model.p_pun_atm_quantity_dispatch = Constraint(model.punBids, rule=p_pun_atm_quantity_dispatch_rule)

        if options.DEBUG:
            logging.info("Creating Merit order constraints")
        merit_order_idx = 0
        if not relax_PUN:
            for p in model.periods:
                pun_orders_sorted_by_mo = sorted(self.pun_orders_by_period[p], key=lambda k: k.merit_order)

                previous_order = pun_orders_sorted_by_mo.pop(0) if pun_orders_sorted_by_mo else None
                while previous_order and pun_orders_sorted_by_mo:
                    next_order = pun_orders_sorted_by_mo.pop(0)
                    if previous_order.price == MAX_PRICE:
                        previous_order = next_order
                        continue

                    mo_expr = model.ugk[self.pun_orders_ids[previous_order]] >= model.ugk[
                        self.pun_orders_ids[next_order]]
                    merit_order_idx += 1
                    setattr(model, "merit_order_%d" % merit_order_idx, Constraint(expr=mo_expr))
                    previous_order = next_order

        if options.DEBUG:
            logging.info("Created %d Merit order constraints" % merit_order_idx)

        if options.DEBUG:
            logging.info("Creating price order constraints")
        merit_order_idx = 0
        if not relax_PUN:
            for p in model.periods:
                pun_orders_sorted_by_price = sorted(self.pun_orders_by_period[p], key=lambda k: -k.price)

                previous_order = pun_orders_sorted_by_price.pop(0) if pun_orders_sorted_by_price else None
                while previous_order and pun_orders_sorted_by_price:
                    next_order = pun_orders_sorted_by_price.pop(0)
                    if previous_order.price == MAX_PRICE:
                        previous_order = next_order
                        continue

                    if previous_order.price > next_order.price:  # two orders can have the same price
                        horizontal_price = next_order.price
                        previous_id = self.pun_orders_ids[previous_order]
                        while horizontal_price == next_order.price:
                            next_id = self.pun_orders_ids[next_order]
                            mo_expr = (model.uek[next_id] <= model.ugk[previous_id] - model.ugk[next_id])

                            merit_order_idx += 1
                            setattr(model, "price_order_%d" % merit_order_idx, Constraint(expr=mo_expr))
                            if pun_orders_sorted_by_price:
                                stored_order = next_order
                                next_order = pun_orders_sorted_by_price.pop(0)
                            else:
                                break
                        next_order = stored_order

                    previous_order = next_order

        if options.DEBUG:
            logging.info("Created %d price order constraints" % merit_order_idx)

        if options.DEBUG:
            logging.info("Creating ATM merit order constraints depending on market split")

        if not relax_PUN:
            order_idx = 0
            for p in model.periods:
                for hBid in self.pun_orders_by_period[p]:
                    # skip price=3000 case
                    if hBid.price == MAX_PRICE:
                        continue
                    h = self.pun_orders_ids[hBid]
                    for kBid in self.pun_orders_by_period[p]:
                        # skip price=3000 case
                        if kBid.price == MAX_PRICE:
                            continue
                        k = self.pun_orders_ids[kBid]
                        if hBid.merit_order < kBid.merit_order \
                                and hBid.price == kBid.price:
                            i = hBid.location
                            j = kBid.location
                            # same zone
                            if i == j:
                                expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k]
                                setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                order_idx += 1

                                expr = model.uek[h] >= model.uek[k]
                                setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                order_idx += 1

                                expr = model.ddk[h] >= hBid.volume * model.udk[k]
                                setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                order_idx += 1

                                #print book.bids[h].id, book.bids[k].id, self.zones[i].name

                                continue

                            if options.SPLIT:
                                # zone connected directly
                                if model.flow_max[i, j, p] > 0 or model.flow_max[j, i, p] > 0:
                                    expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k] \
                                           - hBid.volume * model.uf[i, j, p] - hBid.volume * model.uf[
                                               j, i, p]
                                    setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                    order_idx += 1

                                    expr = model.uek[h] >= model.uek[k] \
                                           - model.uf[i, j, p] - model.uf[j, i, p]
                                    setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                    order_idx += 1

                                    expr = model.ddk[h] >= hBid.volume * model.udk[k] \
                                           - hBid.volume * model.uf[i, j, p] - hBid.volume * model.uf[
                                               j, i, p]
                                    setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                    order_idx += 1

                                    #print book.bids[h].id, book.bids[k].id, self.zones[i].name, "->", self.zones[j].name

                                    continue

                                # zones connected with 1, 2, 3, or 4 middle zones
                                remaining_zones = model.LpunExt.data() - set([i, j])

                                middle_zones = set((z1, z2, z3, z4) for (z1, z2, z3, z4)
                                                in itertools.product(remaining_zones, remaining_zones, remaining_zones, remaining_zones)
                                                if z1 != z2 and z1 != z3 and z1 != z4 \
                                                            and z2 != z3 and z2 != z4 \
                                                                         and z3 != z4)
                                processed = set()
                                for (z1, z2, z3, z4) in middle_zones:
                                    # one zone in the middle
                                    if (model.flow_max[i, z1, p] > 0 and model.flow_max[z1, j, p] > 0) \
                                            or \
                                            (model.flow_max[j, z1, p] > 0 and model.flow_max[z1, i, p] > 0):

                                        if (i,z1,j) in processed:
                                            continue
                                        else:
                                            processed.add((i, z1, j))
                                            processed.add((j, z1, i))

                                        expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, j, p] - hBid.volume * \
                                               model.uf[j, z1, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.uek[h] >= model.uek[k] \
                                               - model.uf[i, z1, p] - model.uf[z1, i, p] \
                                               - model.uf[z1, j, p] - model.uf[j, z1, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.ddk[h] >= hBid.volume * model.udk[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, j, p] - hBid.volume * \
                                               model.uf[j, z1, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        #print book.bids[h].id, book.bids[k].id, self.zones[i].name, "->", self.zones[z1].name, "->", self.zones[j].name


                                    # two zones in the middle
                                    if (model.flow_max[i, z1, p] > 0 and model.flow_max[z1, z2, p] > 0 and
                                        model.flow_max[
                                            z2, j, p] > 0) \
                                            or \
                                            (model.flow_max[j, z2, p] > 0 and model.flow_max[z2, z1, p] > 0 and
                                             model.flow_max[
                                                 z1, i, p] > 0):

                                        if (i,z1,z2,j) in processed:
                                            continue
                                        else:
                                            processed.add((i, z1, z2, j))
                                            processed.add((j, z2, z1, i))

                                        expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, j, p] - hBid.volume * \
                                               model.uf[j, z2, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.uek[h] >= model.uek[k] \
                                               - model.uf[i, z1, p] - model.uf[z1, i, p] \
                                               - model.uf[z1, z2, p] - model.uf[z2, z1, p] \
                                               - model.uf[z2, j, p] - model.uf[j, z2, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.ddk[h] >= hBid.volume * model.udk[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, j, p] - hBid.volume * \
                                               model.uf[j, z2, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        #print book.bids[h].id, book.bids[k].id, self.zones[i].name, "->", self.zones[z1].name, "->", \
                                        #      self.zones[z2].name, "->", self.zones[j].name



                                    # three zones in the middle
                                    if (model.flow_max[i, z1, p] > 0 and model.flow_max[z1, z2, p] > 0 and
                                        model.flow_max[
                                            z2, z3, p] > 0 and model.flow_max[z3, j, p] > 0) \
                                            or \
                                            (model.flow_max[j, z3, p] > 0 and model.flow_max[z3, z2, p] > 0 and
                                             model.flow_max[
                                                 z2, z1, p] > 0 and model.flow_max[z1, i, p] > 0):

                                        if (i,z1,z2,z3,j) in processed:
                                            continue
                                        else:
                                            processed.add((i, z1, z2, z3, j))
                                            processed.add((j, z3, z2, z1, i))

                                        expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, z3, p] - hBid.volume * \
                                               model.uf[z3, z2, p] \
                                               - hBid.volume * model.uf[z3, j, p] - hBid.volume * \
                                               model.uf[j, z3, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.uek[h] >= model.uek[k] \
                                               - model.uf[i, z1, p] - model.uf[z1, i, p] \
                                               - model.uf[z1, z2, p] - model.uf[z2, z1, p] \
                                               - model.uf[z2, z3, p] - model.uf[z3, z2, p] \
                                               - model.uf[z3, j, p] - model.uf[j, z3, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.ddk[h] >= hBid.volume * model.udk[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, z3, p] - hBid.volume * \
                                               model.uf[z3, z2, p] \
                                               - hBid.volume * model.uf[z3, j, p] - hBid.volume * \
                                               model.uf[j, z3, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        #print book.bids[h].id, book.bids[k].id, self.zones[i].name, "->", self.zones[z1].name, "->", \
                                        #    self.zones[z2].name, "->", self.zones[z3].name, "->", self.zones[j].name



                                    # 4 zones in the middle
                                    if (model.flow_max[i, z1, p] > 0 and model.flow_max[z1, z2, p] > 0 and
                                        model.flow_max[
                                            z2, z3, p] > 0 and model.flow_max[z3, z4, p] > 0 and model.flow_max[
                                            z4, j, p] > 0) \
                                            or \
                                            (model.flow_max[j, z4, p] > 0 and model.flow_max[z4, z3, p] > 0 and
                                             model.flow_max[
                                                 z3, z2, p] > 0 and model.flow_max[z2, z1, p] > 0 and model.flow_max[
                                                 z1, i, p] > 0):

                                        if (i,z1,z2,z3,z4,j) in processed:
                                            continue
                                        else:
                                            processed.add((i, z1, z2, z3, z4, j))
                                            processed.add((j, z4, z3, z2, z1, i))

                                        expr = model.dwk[h] + model.ddk[h] >= hBid.volume * model.uek[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, z3, p] - hBid.volume * \
                                               model.uf[z3, z2, p] \
                                               - hBid.volume * model.uf[z3, z4, p] - hBid.volume * \
                                               model.uf[z4, z3, p] \
                                               - hBid.volume * model.uf[z4, j, p] - hBid.volume * \
                                               model.uf[j, z4, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.uek[h] >= model.uek[k] \
                                               - model.uf[i, z1, p] - model.uf[z1, i, p] \
                                               - model.uf[z1, z2, p] - model.uf[z2, z1, p] \
                                               - model.uf[z2, z3, p] - model.uf[z3, z2, p] \
                                               - model.uf[z3, z4, p] - model.uf[z4, z3, p] \
                                               - model.uf[z4, j, p] - model.uf[j, z4, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        expr = model.ddk[h] >= hBid.volume * model.udk[k] \
                                               - hBid.volume * model.uf[i, z1, p] - hBid.volume * \
                                               model.uf[z1, i, p] \
                                               - hBid.volume * model.uf[z1, z2, p] - hBid.volume * \
                                               model.uf[z2, z1, p] \
                                               - hBid.volume * model.uf[z2, z3, p] - hBid.volume * \
                                               model.uf[z3, z2, p] \
                                               - hBid.volume * model.uf[z3, z4, p] - hBid.volume * \
                                               model.uf[z4, z3, p] \
                                               - hBid.volume * model.uf[z4, j, p] - hBid.volume * \
                                               model.uf[j, z4, p]
                                        setattr(model, "ATM_split_order_%d" % order_idx, Constraint(expr=expr))
                                        order_idx += 1

                                        #print book.bids[h].id, book.bids[k].id, self.zones[i].name, "->", self.zones[z1].name, "->", \
                                        #    self.zones[z2].name, "->", self.zones[z3].name, "->", \
                                        #    self.zones[z4].name, "->", self.zones[j].name



            if options.DEBUG:
                logging.info("Created %d ATM split constraints" % order_idx)

        # if options.DEBUG:
        #     logging.info("Creating uf definitions" )
        #
        # order_idx_uf=0
        # for (i,j,p) in model.LpunExt*model.LpunExt*model.periods:
        #     if model.flow_max[i,j,p]>0:
        #         # for the first constraint BigM=1, as long as UF_EPSILON < 1
        #         expr = model.f[i, j, p] <= model.flow_max[i, j, p] - UF_EPSILON + model.uf[i, j, p]
        #         setattr(model, "UF_constraint_A_%d" % order_idx_uf, Constraint(expr=expr))
        #         expr = model.f[i, j, p] >= model.flow_max[i, j, p] \
        #                - (model.flow_max[i, j, p] + model.flow_max[j, i, p])*(1-model.uf[i, j, p])
        #         setattr(model, "UF_constraint_B_%d" % order_idx_uf, Constraint(expr=expr))
        #         order_idx_uf+=1
        #     else:
        #         model.uf[i,j,p].fix(0)
        #         self.nbinvar-=1
        #
        # if options.DEBUG:
        #     order_idx_uf=2*order_idx_uf
        #     logging.info("Created %d constraints" % order_idx_uf)

        # only loose definition of uf
        # it appears to be more efficient
        def p_uf_def_rule(m, i, j, p):
            if m.flow_max[i, j, p] > 0:
                return m.uf[i, j, p] <= (m.f[i, j, p] + m.flow_max[j, i, p]) / \
                       (m.flow_max[i, j, p] + m.flow_max[j, i, p])
            else:
                m.uf[i, j, p].fix(0)
                self.nbinvar -= 1
                return Constraint.Skip

        if options.DEBUG:
            logging.info("Creating uf definitions")
        if options.SPLIT and not relax_PUN:
            model.p_uf_def = Constraint(model.LpunExt, model.LpunExt, model.periods, rule=p_uf_def_rule)

        def p_pun_quantity_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return m.dkpi[b] == m.ugk[b] * bid.volume + m.dwk[b] + m.ddk[b]

        if not relax_PUN:
            model.p_pun_quantity = Constraint(model.punBids, rule=p_pun_quantity_rule)

        def p_binary_expansion_rule(m, t, l):
            rhs = 0

            for pun_bid in self.pun_orders_by_period[t]:
                if pun_bid.location == l:
                    rhs += m.ddk[self.pun_orders_ids[pun_bid]]

            return 1e-3 * sum(m.bexp[t, j, l] * 2 ** j for j in model.binary_powers) == rhs

        if not relax_PUN:
            model.p_binary_expansion = Constraint(model.periods, model.Lpun, rule=p_binary_expansion_rule)

        # PUN constraint
        def p_pun_defintion_rule(m, p):
            lhs = 0
            rhs = m.imbalance[p]

            for b in m.punBids:
                pun_bid = book.bids[b]
                if pun_bid.period != p:
                    continue

                lhs += pun_bid.volume * m.yugPUNk[b]
                lhs += pun_bid.price * m.ddk[b]

                rhs += pun_bid.volume * m.yugPzk[b]
                rhs -= pun_bid.volume * m.yuwvphik[b]

            for (j, l) in (model.binary_powers * model.Lpun):
                rhs += 1e-3 * m.ybPzi[p, j, l] * 2 ** j

            return lhs == rhs

        if options.DEBUG:
            logging.info("Creating PUN price constraint")
        if not relax_PUN:
            model.p_pun_defintion = Constraint(model.periods, rule=p_pun_defintion_rule)

        # Lower level
        if options.DEBUG:
            logging.info("Creating lower level problem constraints")

        def p_max_PUN_demand_volume_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return m.dwk[b] <= m.uwk[b] * book.bids[b].volume

        model.p_max_PUN_demand_volume = Constraint(model.punBids, rule=p_max_PUN_demand_volume_rule)

        def p_max_demand_volume_rule(m, b):
            return m.dk[b] <= -book.bids[b].volume

        model.p_max_demand_volume = Constraint(model.demandBids, rule=p_max_demand_volume_rule)

        def p_max_supply_volume_rule(m, b):
            return m.sp[b] <= book.bids[b].volume

        model.p_max_supply_volume = Constraint(model.supplyBids, rule=p_max_supply_volume_rule)

        def p_max_flow_rule(m, local, foreign, p):
            return m.f[local, foreign, p] <= m.flow_max[local, foreign, p]

        model.p_max_flow = Constraint(model.L, model.L, model.periods, rule=p_max_flow_rule)

        def p_flows_rule(m, local, foreign, p):
            return m.f[local, foreign, p] == -m.f[foreign, local, p]

        model.p_flows = Constraint(model.L, model.L, model.periods, rule=p_flows_rule)

        def p_block_max_rule(m, b):
            return m.rp[b] <= m.ubp[b]

        model.p_block_max = Constraint(model.bBids, rule=p_block_max_rule)

        def p_block_min_rule(m, b):
            bid = book.bids[b]
            return -m.rp[b] <= -m.ubp[b] * bid.min_acceptance_ratio

        model.p_block_min = Constraint(model.bBids, rule=p_block_min_rule)

        def p_balance_rule(m, p, l):
            demand = sum(m.dk[b] for b in model.demandBids if (book.bids[b].period == p and book.bids[b].location == l))

            demand += sum(m.dwk[b] for b in model.punBids if (book.bids[b].period == p and book.bids[b].location == l))
            if not relax_PUN:
                demand += sum((book.bids[b].volume * m.ugk[b] + m.ddk[b])
                              for b in model.punBids if (book.bids[b].period == p and book.bids[b].location == l))

            supply = sum(m.sp[b] for b in model.supplyBids if (book.bids[b].period == p and book.bids[b].location == l))
            supply += sum(m.rp[b] * book.bids[b].volumes[p] for b in model.bBids if book.bids[b].location == l)

            flow_out = 0
            for foreign in model.L:
                flow_out += m.f[l, foreign, p]

            return demand + flow_out == supply

        model.p_balance = Constraint(model.periods, model.L, rule=p_balance_rule)

        # Dual constraints
        if options.DEBUG:
            logging.info("Creating dual constraints")

        def d_zonal_price_PUN_rule(m, b):
            bid = book.bids[b]
            return m.vphikPUNw[b] + m.pZi[bid.location, bid.period] >= bid.price

        model.d_zonal_price_PUN = Constraint(model.punBids, rule=d_zonal_price_PUN_rule)

        def d_zonal_price_demand_rule(m, b):
            bid = book.bids[b]
            return m.vphiknonPUNw[b] + m.pZi[bid.location, bid.period] >= bid.price

        model.d_zonal_price_demand = Constraint(model.demandBids, rule=d_zonal_price_demand_rule)

        def d_zonal_price_supply_rule(m, b):
            bid = book.bids[b]
            return m.vphip[b] - m.pZi[bid.location, bid.period] >= - bid.price

        model.d_zonal_price_supply = Constraint(model.supplyBids, rule=d_zonal_price_supply_rule)

        def d_flows_rule(m, local, foreign, p):
            return m.deltaMax[local, foreign, p] + m.etaij[local, foreign, p] \
                   + m.etaij[foreign, local, p] + m.pZi[local, p] == 0

        model.d_flows = Constraint(model.L, model.L, model.periods, rule=d_flows_rule)

        def d_block_rule(m, b):
            bid = book.bids[b]
            l = bid.location
            return m.vphibMax[b] - m.vphibMin[b] + sum(
                bid.volumes[p] * (bid.price - m.pZi[l, p]) for p in model.periods) == 0

        model.d_block = Constraint(model.bBids, rule=d_block_rule)

        # Linearization and auxiliary variables definition
        if options.DEBUG:
            logging.info("Creating linearization constraints")

        # ugtk_pun
        def lin_ugtk_pun_first_LB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return -M_ugtk_pun_lower * m.ugk[b] <= m.yugPUNk[b]

        if not relax_PUN:
            model.lin_ugtk_pun_first_LB = Constraint(model.punBids, rule=lin_ugtk_pun_first_LB_rule)

        def lin_ugtk_pun_first_UB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return M_ugtk_pun_upper * m.ugk[b] >= m.yugPUNk[b]

        if not relax_PUN:
            model.lin_ugtk_pun_first_UB = Constraint(model.punBids, rule=lin_ugtk_pun_first_UB_rule)

        def lin_ugtk_pun_second_LB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return -M_ugtk_pun_lower * (1 - m.ugk[b]) <= m.pi[bid.period] - m.yugPUNk[b]

        if not relax_PUN:
            model.lin_ugtk_pun_second_LB = Constraint(model.punBids, rule=lin_ugtk_pun_second_LB_rule)

        def lin_ugtk_pun_second_UB_rule(m, b):
            bid = book.bids[b]
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return m.yugPUNk[b] == m.pi[bid.period]
            return M_ugtk_pun_upper * (1 - m.ugk[b]) >= m.pi[bid.period] - m.yugPUNk[b]

        if not relax_PUN:
            model.lin_ugtk_pun_second_UB = Constraint(model.punBids, rule=lin_ugtk_pun_second_UB_rule)

        # ugtk_nonpun
        def lin_ugtk_nonpun_first_LB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return -M_ugtk_non_pun_lower * m.ugk[b] <= m.yugPzk[b]

        if not relax_PUN:
            model.lin_ugtk_nonpun_first_LB = Constraint(model.punBids, rule=lin_ugtk_nonpun_first_LB_rule)

        def lin_ugtk_nonpun_first_UB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            return M_ugtk_non_pun_upper * m.ugk[b] >= m.yugPzk[b]

        if not relax_PUN:
            model.lin_ugtk_nonpun_first_UB = Constraint(model.punBids, rule=lin_ugtk_nonpun_first_UB_rule)

        def lin_ugtk_nonpun_second_LB_rule(m, b):
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return Constraint.Skip
            bid = book.bids[b]
            return -M_ugtk_non_pun_lower * (1 - m.ugk[b]) <= m.pZi[bid.location, bid.period] - m.yugPzk[b]

        if not relax_PUN:
            model.lin_ugtk_nonpun_second_LB = Constraint(model.punBids, rule=lin_ugtk_nonpun_second_LB_rule)

        def lin_ugtk_nonpun_second_UB_rule(m, b):
            bid = book.bids[b]
            if book.bids[b].price == MAX_PRICE and not relax_PUN:
                return m.yugPzk[b] == m.pZi[bid.location, bid.period]
            return M_ugtk_non_pun_upper * (1 - m.ugk[b]) >= m.pZi[bid.location, bid.period] - m.yugPzk[b]

        if not relax_PUN:
            model.lin_ugtk_nonpun_second_UB = Constraint(model.punBids, rule=lin_ugtk_nonpun_second_UB_rule)

        # uwtk, note: yuwvphik is declared NonNegative, then no first_LB
        def lin_uwtk_first_UB_rule(m, b):
            return M_uwtk_upper * m.uwk[b] >= m.yuwvphik[b]

        if not relax_PUN:
            model.lin_uwtk_first_UB = Constraint(model.punBids, rule=lin_uwtk_first_UB_rule)

        def lin_uwtk_second_LB_rule(m, b):
            return -M_uwtk_lower * (1 - m.uwk[b]) <= m.vphikPUNw[b] - m.yuwvphik[b]

        if not relax_PUN:
            model.lin_uwtk_second_LB = Constraint(model.punBids, rule=lin_uwtk_second_LB_rule)

        def lin_uwtk_second_UB_rule(m, b):
            return M_uwtk_upper * (1 - m.uwk[b]) >= m.vphikPUNw[b] - m.yuwvphik[b]

        if not relax_PUN:
            model.lin_uwtk_second_UB = Constraint(model.punBids, rule=lin_uwtk_second_UB_rule)

        # udtk -> binary expansion
        def lin_udtk_first_LB_rule(m, p, l, j):
            return -M_udtk_lower * m.bexp[p, j, l] <= m.ybPzi[p, j, l]

        if not relax_PUN:
            model.lin_udtk_first_LB = Constraint(model.periods, model.Lpun, model.binary_powers,
                                                 rule=lin_udtk_first_LB_rule)

        def lin_udtk_first_UB_rule(m, p, l, j):
            return M_udtk_upper * m.bexp[p, j, l] >= m.ybPzi[p, j, l]

        if not relax_PUN:
            model.lin_udtk_first_UB = Constraint(model.periods, model.Lpun, model.binary_powers,
                                                 rule=lin_udtk_first_UB_rule)

        def lin_udtk_second_LB_rule(m, p, l, j):
            return -M_udtk_lower * (1 - m.bexp[p, j, l]) <= m.pZi[l, p] - m.ybPzi[p, j, l]

        if not relax_PUN:
            model.lin_udtk_second_LB = Constraint(model.periods, model.Lpun, model.binary_powers,
                                                  rule=lin_udtk_second_LB_rule)

        def lin_udtk_second_UB_rule(m, p, l, j):
            return M_udtk_upper * (1 - m.bexp[p, j, l]) >= m.pZi[l, p] - m.ybPzi[p, j, l]

        if not relax_PUN:
            model.lin_udtk_second_UB = Constraint(model.periods, model.Lpun, model.binary_powers,
                                                  rule=lin_udtk_second_UB_rule)

        # ubp -> block bids
        def lin_ubp_max_first_rule(m, b):
            return m.ypMax[b] <= M_block_surplus * book.bids[b].total_volume() * m.ubp[b]

        model.lin_ubp_max_first = Constraint(model.bBids, rule=lin_ubp_max_first_rule)

        def lin_ubp_max_second_rule(m, b):
            return m.vphibMax[b] - m.ypMax[b] <= M_block_surplus * book.bids[b].total_volume() * (1 - m.ubp[b])

        model.lin_ubp_max_second = Constraint(model.bBids, rule=lin_ubp_max_second_rule)

        def lin_ubp_max_second_rule_LO(m, b):
            return 0 <= m.vphibMax[b] - m.ypMax[b]

        model.lin_ubp_max_second_LO = Constraint(model.bBids, rule=lin_ubp_max_second_rule_LO)

        def lin_ubp_min_first_rule(m, b):
            return m.ypMin[b] <= M_block_surplus * book.bids[b].total_volume() * m.ubp[b]

        model.lin_ubp_min_first = Constraint(model.bBids, rule=lin_ubp_min_first_rule)

        def lin_ubp_min_second_rule(m, b):
            return m.vphibMin[b] - m.ypMin[b] <= M_block_surplus * book.bids[b].total_volume() * (1 - m.ubp[b])

        model.lin_ubp_min_second = Constraint(model.bBids, rule=lin_ubp_min_second_rule)

        def lin_ubp_min_second_rule_LO(m, b):
            return 0 <= m.vphibMin[b] - m.ypMin[b]

        model.lin_ubp_min_second_LO = Constraint(model.bBids, rule=lin_ubp_min_second_rule_LO)

        # Strong duality
        if options.DEBUG:
            logging.info("Creating strong duality constraint")

        def primal_obj_lower_level_expr(m):
            expr = sum(book.bids[b].price * m.dk[b] for b in m.demandBids)
            expr += sum(book.bids[b].price * m.dwk[b] for b in m.punBids)
            expr -= sum(book.bids[b].price * m.sp[b] for b in m.supplyBids)
            expr -= sum(book.bids[b].price * m.rp[b] * book.bids[b].total_volume() for b in m.bBids)
            return expr

        def dual_obj_expr(m):
            expr = sum(book.bids[b].volume * (m.vphikPUNw[b]) for b in m.punBids)
            if not relax_PUN:
                expr = sum(book.bids[b].volume * (- m.yugPzk[b] + m.yuwvphik[b]) for b in m.punBids)
            expr += sum(-book.bids[b].volume * (m.vphiknonPUNw[b]) for b in m.demandBids)
            expr += sum(book.bids[b].volume * (m.vphip[b]) for b in m.supplyBids)
            expr += sum(m.ypMax[b] - m.ypMin[b] * book.bids[b].min_acceptance_ratio for b in m.bBids)

            congestion = 0
            for p in model.periods:
                if not relax_PUN:
                    for (j, l) in (model.binary_powers * model.Lpun):
                        expr -= 1e-3 * m.ybPzi[p, j, l] * 2 ** j

                for local in model.L:
                    for foreign in model.L:
                        congestion += m.deltaMax[local, foreign, p] * m.flow_max[local, foreign, p]

            return expr + congestion

        def strong_duality_rule(m):
            return primal_obj_lower_level_expr(m) == dual_obj_expr(m)

        model.strong_duality = Constraint(rule=strong_duality_rule)

        if options.DEBUG:
            logging.info("Creating objective")

        def primal_obj_MILP_expr(m):
            expr = sum(book.bids[b].price * m.dk[b] for b in m.demandBids)
            if relax_PUN:
                expr += sum(book.bids[b].price * m.dwk[b] for b in m.punBids)
            else:
                expr += sum(book.bids[b].price * m.dkpi[b] for b in m.punBids)
            expr -= sum(book.bids[b].price * m.sp[b] for b in m.supplyBids)
            expr -= sum(book.bids[b].price * m.rp[b] * book.bids[b].total_volume() for b in m.bBids)
            return expr

        # Objective
        model.obj = Objective(rule=primal_obj_MILP_expr, sense=maximize)

        # FIX PUN at 3000

        self.fix_window(model, ESTIMATED_PUN_PRICES_RANGES)

        # Branching priorities.
        # Apparently, only .nl files (e.g., used with NEOS) handle Suffix() correctly
        # model.priority = Suffix(direction=Suffix.EXPORT, datatype=Suffix.INT)
        # model.priority.set_value(model.ugk, 1)
        # model.priority.set_value(model.uek, 1)
        # model.priority.set_value(model.uwk, 1)
        # model.priority.set_value(model.udk, 1)
        # model.priority.set_value(model.bexp, 2)

        self.model = model
        # model.pprint()

    def fix_window(self, model, ESTIMATED_PUN_PRICES_RANGES=None):
        if options.DEBUG:
            logging.info("Fixing variables" + ", relaxed PUN" if self.relax_PUN else '')

        if ESTIMATED_PUN_PRICES_RANGES:
            estimated_pun_prices = ESTIMATED_PUN_PRICES_RANGES
        else:
            MAX_PRICE = self.priceCap[1]
            MIN_PRICE = self.priceCap[0]
            estimated_pun_prices = {t: [MIN_PRICE, MAX_PRICE - options.EPS] for t in self.orders.periods}

        book = self.orders
        relax_PUN = self.relax_PUN
        for p in model.punBids:
            period = book.bids[p].period
            if book.bids[p].price > estimated_pun_prices[period][1]:
                if not relax_PUN:
                    model.dkpi[p].value = book.bids[p].volume
                    model.dkpi[p].fixed = True
                    model.ddk[p].value = 0
                    model.ddk[p].fixed = True
                    model.ugk[p].value = 1
                    model.ugk[p].fixed = True
                    model.uek[p].value = 0
                    model.uek[p].fixed = True
                    model.uwk[p].value = 0
                    model.uwk[p].fixed = True
                    model.udk[p].value = 0
                    model.udk[p].fixed = True
                    model.dwk[p].value = 0
                    model.dwk[p].fixed = True
                    self.nbinvar -= 4
                else:
                    model.uwk[p].value = 1
                    model.uwk[p].fixed = True
            elif book.bids[p].price < estimated_pun_prices[period][0]:
                if not relax_PUN:
                    model.dkpi[p].value = 0.0
                    model.dkpi[p].fixed = True
                    model.ddk[p].value = 0
                    model.ddk[p].fixed = True
                    model.ugk[p].value = 0
                    model.ugk[p].fixed = True
                    model.uek[p].value = 0
                    model.uek[p].fixed = True
                    model.uwk[p].value = 0
                    model.uwk[p].fixed = True
                    model.udk[p].value = 0
                    model.udk[p].fixed = True
                    model.dwk[p].value = 0
                    model.dwk[p].fixed = True
                    self.nbinvar -= 4
                else:
                    model.uwk[p].value = 0
                    model.uwk[p].fixed = True
            else:
                if not relax_PUN:
                    model.dkpi[p].fixed = False
                    model.ddk[p].fixed = False
                    model.ugk[p].fixed = False
                    model.uek[p].fixed = False
                    model.uwk[p].fixed = False
                    model.udk[p].fixed = False
                    model.dwk[p].fixed = False
                else:
                    model.uwk[p].fixed = False

    def solve(self, VERBOSE=False, strategy='Simple'):
        """
        Solve the PUN problem
        """

        logging.info('Solving day %d' % self.day_id)
        self.t_solve_init = time.time()

        if strategy == "NEOS":
            self.solve_with_neos()
        elif strategy == "Advanced":
            self.advanced_solve(VERBOSE)
        else:  # Simple
            self.simple_solve(VERBOSE)

    def simple_solve(self, VERBOSE):
        """
        Simple strategy: just call the solver
        """
        results = options.SOLVER.solve(self.model, tee=VERBOSE)

        # Detect infeasibility and relax feas. parameter
        if results.solver.termination_condition == \
                TerminationCondition.infeasible:
            logging.info("Relaxing feasibility parameter.")
            feas = options.SOLVER.options["simplex tolerances feasibility"]
            options.SOLVER.options["simplex tolerances feasibility"] = 1e-6
            results = options.SOLVER.solve(self.model, tee=VERBOSE)
            logging.info("Restoring feasibility parameter.")
            options.SOLVER.options["simplex tolerances feasibility"] = feas

        if len(self.model.solutions) != 0:
            self.t_solve = time.time() - self.t_solve_init
            logging.info("Time: %.2f" % self.t_solve)
            self._build_solution(results)
        else:
            self.exportModel()

    def solve_with_neos(self):
        """
        Similar as the Simple strategy, but on NEOS.
        :return:
        """
        logging.info("Solving model with NEOS using %s." % options.SOLVER_NAME)
        solver_manager = SolverManagerFactory('neos')

        mip_solver = SolverFactory(options.SOLVER_NAME)
        # Pyomo converts the problem in .nl and send it to NEOS.
        # Note: the .nl file correctly handles Suffix() for priority.
        # Options are in AMPL format as in:
        # https://ampl.com/products/solvers/solvers-we-sell/cplex/options/
        mip_solver.options["timelimit"] = 100
        mip_solver.options["mipgap"] = 1e-6
        mip_solver.options["mipemphasis"] = 1
        mip_solver.options["integrality"] = 0
        mip_solver.options["optimality"] = 1e-9
        mip_solver.options["feasibility"] = 1e-9
        mip_solver.options["mipstartalg"] = 1
        mip_solver.options["mircuts"] = 2
        mip_solver.options["flowcuts"] = 2

        if options.DEBUG:
            for (k, v) in mip_solver.options.items():
                print('mip_solver.options["%s"] = %s' % (k, v))

        results = solver_manager.solve(self.model, opt=mip_solver, tee=True, keepfiles=False)
        if results.solver.termination_condition == TerminationCondition.optimal:
            logging.info("Solution found:  %s" % results.solver.termination_condition)
            self.t_solve = time.time() - self.t_solve_init
            logging.info("Time: %.2f" % self.t_solve)
            results.neos = True
            self._build_solution(results)
        else:
            logging.info("Error: Solver Termination Condition: %s" % results.solver.termination_condition)

    def advanced_solve(self, VERBOSE):
        """
        First solve without the PUN constraints. Determine a weighted average price approximationfor the PUN
        Second, solve on a reduced price window around those prices
        Finally, solve over the remaining possibilities, with a good starting point obtained at step 2.
        """

        logging.info("Advanced solution method (ASM)")

        logging.info("ASM phase 1 of 3: Solving model with PUN relaxed")
        # Create a copy
        dam_relaxed = self.loader.read_day(self.day_id)
        dam_relaxed.create_model(relax_PUN=True)

        # reset time to exclude model generation
        self.t_solve_init = time.time()
        logging.info("Reset time to exclude model generation.")

        dam_relaxed.solve(VERBOSE=True, strategy='Simple')

        # Retrieve relaxed PUN prices from relaxed model
        relaxed_prices_by_period = dam_relaxed.prices(0)
        pun_prices = dam_relaxed.pun_prices()
        estimated_pun_prices_ranges = {}
        for p, v in relaxed_prices_by_period.iteritems():
            estimated_pun_prices_ranges[p] = [v - 1.0, v + 1.0]

        logging.info("Estimated PUN price ranges : %s" % estimated_pun_prices_ranges)

        logging.info("ASM phase 2 of 3: Solving model on restricted price window")

        self.fix_window(self.model, estimated_pun_prices_ranges)
        heuristic_sol = False
        warm_file = "warmstart.sol"

        stored_gap = options.SOLVER.options["mip tolerances mipgap"]
        options.SOLVER.options["mip tolerances mipgap"] = 1e-6
        options.SOLVER.solve(self.model, tee=VERBOSE, keepfiles=True, solnfile=warm_file)
        options.SOLVER.options["mip tolerances mipgap"] = stored_gap

        if len(self.model.solutions) != 0:
            heuristic_sol = True
            self.t_solve = time.time() - self.t_solve_init
            logging.info("Time: %.2f" % self.t_solve)

        logging.info("ASM phase 3 of 3: Proving optimality")

        self.nbinvar = self.nbinvar_initial

        self.fix_window(self.model)
        results = options.SOLVER.solve(self.model, tee=VERBOSE, keepfiles=False,
                             solnfile="full.sol", logfile="full.log",
                             warmstart=heuristic_sol, warmstart_file=warm_file)

        if len(self.model.solutions) != 0:
            self.t_solve = time.time() - self.t_solve_init
            logging.info("Time: %.2f" % self.t_solve)
            self._build_solution(results)
        else:
            self.exportModel()
            raise Exception('No solution found when clearing the day-ahead energy market.')

    def _build_solution(self, results=None):
        """
        Store the solution of the day-ahead market in the order book.
        """
        model = self.model
        book = self.orders

        self.absolute_gap = 1e9
        if results:
            self.absolute_gap = results["Problem"][0]["Upper bound"] - results["Problem"][0]["Lower bound"]
            if hasattr(results, "neos"): # NEOS does not report upper and lower values
                self.solver_message = results["Solver"][0]["Message"]
                logging.info("Solver Message : %s" % self.solver_message)
            elif options.DEBUG:
                logging.info("Absolute gap : %s" % self.absolute_gap)

        book.volumes = {s: {l: {t: 0.0 for t in book.periods} for l in model.L} for s in ['SUPPLY', 'DEMAND']}

        pun_matched = {l: {t: 0.0 for t in book.periods} for l in model.Lpun}

        self.welfare = value(model.obj)
        logging.info("welfare: %.2f" % value(self.welfare))

        self.expansion = False
        try:
            for p in model.udk:
                if value(model.udk[p]) == 1:
                    self.expansion = True
                    break
        except Exception as e:
            print(e)

        for i in model.demandBids:
            bid = book.bids[i]

            # Obtain and save the volume
            volume = model.dk[i].value
            bid.acceptance = abs(volume / bid.volume)

            # Update volumes and prices
            if volume > options.EPS:
                # Compute the total volumes exchanged
                t = bid.period
                book.volumes["DEMAND"][bid.location][t] -= volume

        for i in model.punBids:
            bid = book.bids[i]

            # Obtain and save the volume
            volume = model.dwk[i].value if self.relax_PUN else model.dkpi[i].value
            bid.acceptance = abs(volume / bid.volume)

            # Update volumes and prices
            if volume > options.EPS:
                # Compute the total volumes exchanged
                t = bid.period
                book.volumes["DEMAND"][bid.location][t] -= volume
                pun_matched[bid.location][t] += volume

        for i in model.supplyBids:
            bid = book.bids[i]

            # Obtain and save the volume
            volume = model.sp[i].value
            bid.acceptance = abs(volume / bid.volume)

            # Update volumes and prices
            if volume > options.EPS:
                # Compute the total volumes exchanged
                t = bid.period
                book.volumes["SUPPLY"][bid.location][t] += volume

        for i in model.bBids:
            bid = book.bids[i]

            # Obtain and save the volume
            bid.acceptance = model.rp[i].value

            # Update volumes and prices
            if bid.acceptance > options.EPS:
                # Compute the total volumes exchanged
                for t in model.periods:
                    book.volumes["SUPPLY"][bid.location][t] += bid.volumes[t] * bid.acceptance

        for c in model.C:
            connection = self.connections[c - 1]
            from_id = connection.from_id
            to_id = connection.to_id
            flow_up = []
            flow_down = []
            congestion_up = []
            congestion_down = []
            for p in model.periods:
                flow_up.append(model.f[from_id, to_id, p].value)
                flow_down.append(model.f[to_id, from_id, p].value)
                congestion_up.append(model.etaij[from_id, to_id, p].value)
                congestion_down.append(model.etaij[to_id, from_id, p].value)
            self.connections[c - 1].flow_up = flow_up
            self.connections[c - 1].flow_down = flow_down
            self.connections[c - 1].congestion_up = congestion_up
            self.connections[c - 1].congestion_down = congestion_down

        book.prices = {l: {t: model.pZi[l, t].value for t in book.periods} for l in model.L}
        if not self.relax_PUN:
            book.prices.update({0: {t: model.pi[t].value for t in book.periods}})  # PUN is zone 0 by convention
        else:
            # compute average price over pun zones
            average_price = {}
            for t in book.periods:
                total_pun_macthed = sum([pun_matched[l][t] for l in model.Lpun])
                average_price[t] = sum([model.pZi[l, t].value * pun_matched[l][t] for l in model.Lpun]) \
                                   / total_pun_macthed

            book.prices.update({0: {t: average_price[t] for t in book.periods}})

    def pun_prices(self):
        """Determine pun price range based on PUN orders acceptance"""

        model = self.model
        book = self.orders

        pun_prices = {t: list(self.priceCap) for t in book.periods}
        for i in model.punBids:
            bid = book.bids[i]

            # Obtain and save the volume
            volume = model.dwk[i].value if self.relax_PUN else model.dkpi[i].value
            bid.acceptance = abs(volume / bid.volume)
            if bid.acceptance > 0:
                pun_prices[bid.period][1] = min(pun_prices[bid.period][1], bid.price)
            else:
                pun_prices[bid.period][0] = max(pun_prices[bid.period][0], bid.price)

        return pun_prices

    def pun_price_step(self, prices):
        """

        :param prices: a price by period
        :return: the range of prices of the PUN curve that contains this price
        """
        model = self.model
        book = self.orders

        pun_prices = {t: list(self.priceCap) for t in book.periods}

        for p in book.periods:
            pun_orders_sorted_by_price = sorted(self.pun_orders_by_period[p], key=lambda k: -k.price)

            for bid in pun_orders_sorted_by_price:

                if bid.price > prices[p]:
                    pun_prices[p][1] = bid.price
                elif bid.price < prices[p]:
                    pun_prices[bid.period][0] = bid.price
                    break
                else:
                    pun_prices[bid.period][0] = pun_prices[p][1] = bid.price
                    break

        return pun_prices
