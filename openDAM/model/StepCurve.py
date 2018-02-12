## Step curve of the energy market.
from openDAM.model.Bid import *
from openDAM.model.SinglePeriodBid import *

class StepCurve(Bid):

    def __init__(self, points=[], period=0, location=None):
        """
        Volumes are negative for demand bids.

        :param points: List of volume-price pairs. First pair must have a 0 volume.
        :param period: Period of the bid.
        :param location: Location of the curve
        """
        Bid.__init__(self, location=location)
        assert(len(points) > 0)
        assert(points[0][0] == 0.0)
        self.period = period
        self.bids = self.__points2bids(points)

    def __points2bids(self, points):
        bids = []

        while(len(points) > 1):
            p1 = points.pop(0)
            p2 = points.pop(0)
            bids.append(SinglePeriodBid(p2[0] - p1[0], p1[1], self.period, self.location))

        return bids

    def collect(self):
        return self.bids