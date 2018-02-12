from openDAM.model.SinglePeriodBid import *
from openDAM.model.BlockBid import *

class OrdersBook:
    """
    Structure containting step orders and block bids.
    """

    def __init__(self):
        self.bids = []
        self.periods = set()
        self.prices = None
        self.locations = set()
        self.volumes = None

    def append(self, bid): # TODO declare periods upfront instead of guessing
        """
        Append a bid to the orders book.
        :param bid: Either a SinglePeriodBid or a BlockBid
        """

        self.bids.append(bid)

        # Update the sets
        if bid.location not in self.locations:
            self.locations.add(bid.location)

        if bid.type in ['SB', 'PO']:
            if bid.period not in self.periods:
                self.periods.add(bid.period)
        elif bid.type == 'BB':
            for t in bid.volumes.keys():
                if t not in self.periods:
                    self.periods.add(t)
        else:
            raise "Error"

    def get_last_id(self):
        return len(self.bids)

    def extend(self, bids):
        for b in bids:
            self.append(b)