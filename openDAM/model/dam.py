from __future__ import division

import time

from pyomo.core.base import Constraint, summation, Objective, minimize, ConstraintList, \
    ConcreteModel, Set, RangeSet, Reals, Binary, NonNegativeReals, Var, maximize, Suffix
#from pyomo.core.kernel import value  # Looks like value method changed location in new pyomo version ?
from pyomo.environ import *  # Must be kept
from pyomo.opt import ProblemFormat, SolverStatus, TerminationCondition

import logging

from openDAM.model.OrdersBook import *
import openDAM.conf.options as options

from abc import ABCMeta, abstractmethod


class DAM:
    """
    Model of the day-head electricity market coupling problem
    """

    __metaclass__ = ABCMeta

    def __init__(self, day, zones, curves, blockOrders, connections=None, priceCap=(0, 3000)):
        if connections is None:
            connections = []
        self.day_id = day

        self.zones = zones  #: A dict of Zone objects indexed by zone id
        self.curves = curves
        self.block_orders = blockOrders

        self.connections = connections
        self.priceCap = priceCap  # TODO fix as a function of data and locationc

        # Generate ids for orders
        self.orders = OrdersBook()
        self.plain_single_orders = []  # ids of normal step bids
        self.block_orders_ids = {}

        self.t_solve = 0.0
        self.nbinvar = 0

        self.model = None

    def create_order_book(self):

        for curve in self.curves:
            self.submit(curve)

        for bo in self.block_orders:
            self.submit(bo)

    def submit(self, bid):
        """
        Submit a bid to the market

        Args:
            bid: any type of bid.
        """

        bids = bid.collect()

        startId = self.orders.get_last_id()
        endId = startId + len(bids)
        newBidsIds = range(startId, endId)
        self.orders.extend(bids)

        if bid.type == 'CO':
            self.complex_single_orders.extend(newBidsIds)
        elif bid.type == 'PO':
            self.pun_orders_ids[bid] = newBidsIds[0]
        elif bid.type == 'BB':
            self.block_orders_ids[bid] = newBidsIds[0]
        else:
            self.plain_single_orders.extend(newBidsIds)

        return newBidsIds

    @abstractmethod
    def create_model(self):
        pass

    @abstractmethod
    def solve(self, VERBOSE=False, **kwargs):
        pass

    @abstractmethod
    def _build_solution(self):
        pass

    def exportModel(self):
        """
        Export the model in LP format.
        """
        self.model.write(filename="damClearing.lp", format=ProblemFormat.cpxlp,
                         io_options={"symbolic_solver_labels": True})

    def volumes(self, supplydemand='SUPPLY', location=None):
        """
        Get the cleared volumes.

        :param supplydemand: either SUPPLY or DEMAND.
        :param location: Zone.
        """
        return self.orders.volumes[supplydemand][location]

    def prices(self, location=None):
        """
        Get the system marginal prices.

        :param location: Location.
        """
        return self.orders.prices[location]
