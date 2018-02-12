from openDAM.model.Bid import *


class PunOrder(Bid):
    """
    Model of a PUN order
    """

    def __init__(self, id, location, period, merit_order, volume, price):
        Bid.__init__(self, location, type='PO')
        self.id = id
        self.period = period  #: Period of the bid.
        self.merit_order = merit_order  #: Merit order of the bid.
        self.volume = volume  #: Volume of the bid.
        self.price = price  #: Limit price of the bid.

    def collect(self):
        return [self]
