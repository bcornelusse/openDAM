import abc

class Bid(object):
    """
    Abstract class for all types of Bids.
    """
    __metaclass__ = abc.ABCMeta
    def __init__(self, location=None, type='B'):
        self.acceptance = None #: Acceptance variable, in [0,1], result of the computation
        self.location = location #: Zone where the bid is located
        self.type = type #: Type of bid

    @abc.abstractmethod
    def collect(self):
        """
        Call this method to add the order to the orderbook. Need be reimplemented in classes inheriting from Bid.
        """
        pass
