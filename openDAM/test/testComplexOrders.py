import unittest

from openDAM.model.dam import *
from openDAM.dataio import dam_db_loader
from openDAM.dataio import dam_results_csv

PATH = '../../data/tests'
DATABASE = 'tests.sl3'

class InitTestCase(unittest.TestCase):

    def setUp(self):
        self.path = PATH
        self.database = DATABASE

        # Logging config
        num_log_level = getattr(logging, 'DEBUG', None)
        if not isinstance(num_log_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)
        logging.basicConfig(level=num_log_level)
        self.VERBOSE = num_log_level <= logging.DEBUG

        self.loader = dam_db_loader.Loader(self.path, self.database)

class ComplexOrderCase(InitTestCase):

    def test_1_unmodified(self):
        """
        Basic test:

        * 4 periods,
        * 2 zones,
        * two identical supply complex orders except VT and ramping conditions: order 1 has a large VT, ramp up and ramp down conditions.
        * price taking demand in both zones, with quantity varying in zone 1
        * data is set up so that order 1 is rejected, order 2 is accepted.
        * Hence not enough supply to match the demand at period 3
        """
        dam = self.loader.read_day(1)
        dam.create_model()
        dam.solve(VERBOSE=True)

        for co in dam.complexOrders:
            if co.complex_id == 1:
                self.assertAlmostEqual(co.acceptance, 0, 5)
            elif co.complex_id == 2:
                self.assertAlmostEqual(co.acceptance, 1, 5)

        p1 = dam.prices(1)
        p2 = dam.prices(2)

    def test_2_unmodified(self):
        """
        Basic test:

        * 4 periods,
        * 2 zones,
        * two identical supply complex orders except VT and ramping conditions: order 1 has a large VT, ramp up and ramp down conditions.
        * two zones,
        * price taking demand in both zones, with quantity varying in zone 1
        * data is set up so that order 1 is rejected, order 2 is accepted.
        * Demand can be met at all the periods.
        """
        dam = self.loader.read_day(2)


        dam.create_model()
        dam.solve(VERBOSE=True)

        for co in dam.complexOrders:
            if co.complex_id == 1:
                self.assertAlmostEqual(co.acceptance, 0, 5)
            elif co.complex_id == 2:
                self.assertAlmostEqual(co.acceptance, 1, 5)

        p1 = dam.prices(1)
        p2 = dam.prices(2)
        vs1 = dam.volumes('DEMAND', 1)
        vs2 = dam.volumes('DEMAND', 2)

    def test_noMIC(self):
        """
        Starting conditions identical to py:function:test_1_unmodified.

        * Removing the MIC condition.
        * Hence no complex order should be rejected.
        """
        dam = self.loader.read_day(1)
        # Deactivating orders
        for co in dam.complexOrders:
            co.VT = 0
            co.FT = 0

        dam.create_model()
        dam.solve(VERBOSE=True)

        for co in dam.complexOrders:
            if co.complex_id == 1:
                self.assertAlmostEqual(co.acceptance, 1, 5)
            elif co.complex_id == 2:
                self.assertAlmostEqual(co.acceptance, 1, 5)


    def test_noRamping(self):
        """
        Starting conditions identical to py:function:test_1_unmodified.

        * Removing the ramping constraints of order 1.
        * Increasing the MIC condition of order 2.
        * Hence complex order 2 should be rejected instead of order 1.
        """
        dam = self.loader.read_day(1)
        # Deactivating orders
        for co in dam.complexOrders:
            if co.complex_id == 1:
                co.ramp_down = None
                co.ramp_up = None
                co.VT = 10
            if co.complex_id == 2:
                co.FT = 1000
                co.VT = 1000

        dam.create_model()
        dam.solve(VERBOSE=True)

        for co in dam.complexOrders:
            if co.complex_id == 1:
                self.assertAlmostEqual(co.acceptance, 1, 5)
            elif co.complex_id == 2:
                self.assertAlmostEqual(co.acceptance, 0, 5)


if __name__ == '__main__':
    unittest.main()
