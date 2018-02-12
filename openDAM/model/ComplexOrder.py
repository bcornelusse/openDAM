from openDAM.model.Bid import *
from openDAM.model.StepCurve import *

class ComplexOrder(Bid):
    """
    Complex order, i.e. a step curve for each period, plus optionally a MIC constraint, ramp up/down constraints, and scheduled stop constraints.

    :param curves: Dictionary where the key are periods and values are step curves.
    :param FT: Fixed cost to be recovered (MIC condition)
    :param VT: Variable cost to be recoverd (MIC condition)
    :param ramp_down: Limit on the downward variation of the accepted volume between consecutive periods
    :param ramp_up: Limit on the upward variation of the accepted volume between consecutive periods
    :param SSperiods: Scheduled stop condition, i.e. number of periods to consider for shut down
    :param location: a zone id.
    """

    def __init__(self, id=0, curves={}, FT=0.0, VT=0.0, LG_down=None, LG_up=None, SSperiods=0, location=None):
        Bid.__init__(self, location=location, type='CO')
        self.complex_id = id
        self.curves = curves
        self.FT = FT
        self.VT = VT
        self.ramp_down = LG_down
        self.ramp_up = LG_up
        self.SSperiods = SSperiods
        self.ids = [] # Ids assigned when submitted, to be able to map to hourly step orders
        self.surplus = None
        self.volumes = []
        self.pi_lg = []
        self.tentativeVolumes = {}
        self.tentativeIncome = 0
        self.isPR = False

    def collect(self):
        all_bids = []
        for c in self.curves.values():
            all_bids.extend(c.collect())
        return all_bids

    def set_ids(self, ids):
        self.ids = ids