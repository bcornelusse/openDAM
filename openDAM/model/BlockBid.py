from openDAM.model.Bid import *

class BlockBid(Bid):
    """
    Model of a block bid

    :param volumes: dictionary where keys are periods and values are the volumes, positive for production.
    :param price: Limit price of the bid.
    :param location: Zone where bid
    """
    def __init__(self, id, volumes=None, price=0.0, location=None, min_acceptance_ratio=0.0):
        Bid.__init__(self, location, type='BB')
        if volumes is None:
            volumes = {}
        self.id = id
        self.volumes = volumes #: dictionary where keys are periods and values are the volumes, positive for production.
        self.price = price #: Limit price of the bid.
        self.min_acceptance_ratio = min_acceptance_ratio

    def total_volume(self):
        return sum(self.volumes.values())

    def collect(self):
        return [self]
