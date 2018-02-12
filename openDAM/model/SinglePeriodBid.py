from openDAM.model.Bid import *

## Single period bid of the energy market.
class SinglePeriodBid(Bid):
    """
    :param volume: Volume of the bid, positive for production.
    :param price: Cost per unit of volume.
    :param period: Period of the bid.
    :param location: Location.
    """
    def __init__(self, volume=0.0, price=0.0, period=0, location=None):
        Bid.__init__(self, location=location, type='SB')
        self.volume = volume #: Volume of the bid.
        self.price = price #: Limit price of the bid.
        self.period = period #: Period of the bid.

    def collect(self):
        return [self]

    ## @var volume
    # Volume of the bid, positive for production.
    ## @var cost
    # Marginal cost of the bid.
    ## @var period
    #
