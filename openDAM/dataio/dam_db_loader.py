import logging
import sqlite3

import openDAM.conf.options as options
from openDAM.dataio.create_dam_db_from_csv import get_col_names, TABLES
from openDAM.model.ComplexOrder import *
from openDAM.model.Line import *
from openDAM.model.PunOrder import PunOrder
from openDAM.model.BlockBid import BlockBid
from openDAM.model.Zone import *
from openDAM.model.complex_order_model import COMPLEX_DAM
from openDAM.model.pun_dam_model import PUN_DAM


class Loader:

    def __init__(self, db_path, db_name):
        """
        Generate an instance of the :py:class:DAM from a sqlite database.

        IMPORTANT: some general options deactivate reading of some columns. E.g. if options.APPLY MIC is False,
        we set FT abd VT = 0 irrespectively of their value in the database

        :param db_path: Path to the folder containing the sqlite database.
        :param db_name: name of the sqlite3 file.
        """

        self.conn = sqlite3.connect("%s/%s" % (db_path, db_name))  #: connection to the database
        self.curs = self.conn.cursor()  #: cursor to the database
        self.day_id = None  #: the day that is considered
        self.n_periods = None  #: The number of periods of that day
        self.curves_colnames = ['CURVE_ID', 'ZONE_ID', 'PERIOD', 'TYPE']
        self.curves_cols = dict(zip(self.curves_colnames, range(len(self.curves_colnames))))
        self.curve_data_colnames = ['CURVE_ID', 'QUANTITY', 'PRICE']
        self.curve_data_cols = dict(zip(self.curve_data_colnames, range(len(self.curve_data_colnames))))

    def get_all_days(self):
        """
        Returns a list of  all the days present in the database.
        """
        self.curs.execute('select day_id from DAYS order by day_id')
        all_days = [x[0] for x in self.curs.fetchall()]
        return all_days

    def read_day(self, day):
        """
        Read a particular day in the database.

        :param day: the day to read.
        :return: a DAM object.
        """

        self.day_id = day

        logging.info('Reading day %d' % self.day_id)

        self._read_day_info(day)
        zones = self._read_zones()
        curves = self._read_curves()
        complex_orders = self._read_complex_orders()
        block_orders = self._read_block_orders()
        lines = self._read_lines()
        pun_orders = self._read_PUN_orders()

        assert (not (complex_orders and pun_orders))

        if pun_orders:
            return PUN_DAM(day, zones, curves, block_orders, pun_orders, lines, loader=self)
        else:
            return COMPLEX_DAM(day, zones, curves, block_orders, pun_orders, lines)

    def _read_day_info(self, day):
        self.curs.execute('select NPERIODS from DAYS where day_id = %d' % day)
        self.n_periods = int(self.curs.fetchall()[0][0])

    def _read_zones(self):
        zone_colnames = ['ZONE_ID', 'NAME', 'MINIMUMPRICE', 'MAXIMUMPRICE']
        zone_cols = dict(zip(zone_colnames, range(len(zone_colnames))))
        self.curs.execute(
            'select %s from ZONES where day_id = %d order by ZONE_ID' % (', '.join(zone_colnames), self.day_id))

        all_zones = {}
        for z in self.curs.fetchall():
            all_zones[z[zone_cols['ZONE_ID']]] = Zone(z[zone_cols['ZONE_ID']], z[zone_cols['NAME']],
                                                      z[zone_cols['MINIMUMPRICE']], z[zone_cols['MAXIMUMPRICE']])
        return all_zones

    def _read_curves(self):
        self.curs.execute('select %s from CURVES where day_id = %d order by CURVE_ID' % (
            ', '.join(self.curves_colnames), self.day_id))
        curves = self.curs.fetchall()

        self.curs.execute('select %s from CURVE_DATA where day_id = %d order by CURVE_ID, POSITION' % (
            ', '.join(self.curve_data_colnames), self.day_id))
        curve_data = self.curs.fetchall()

        return self._create_curves(curves, curve_data)

    def _create_curves(self, list_of_curves, points):
        """
        Note: no check whether a step curve could contain non flat segments

        :param list_of_curves: contains definition of curves as a list
        :param points: points contains coordinates defining the curves, for all the curves in list_of_curves
        :return: a list of StepCurve
        """

        c_cols = self.curves_cols
        d_cols = self.curve_data_cols

        curves = []
        point_index = 0  # Index to iterate over all the points
        for curve in list_of_curves:
            c_id = curve[c_cols['CURVE_ID']]
            c_type = curve[c_cols['TYPE']]
            c_points = []
            while point_index < len(points):
                p = points[point_index]
                if p[d_cols['CURVE_ID']] == c_id:
                    quantity = p[d_cols['QUANTITY']]
                    price = p[d_cols['PRICE']]
                    c_points.append((quantity if c_type == 'SUPPLY' else -quantity, price))
                    point_index += 1
                else:
                    break
            sc = StepCurve(points=c_points, period=curve[c_cols['PERIOD']],
                           location=curve[c_cols['ZONE_ID']])
            curves.append(sc)

        return curves

    def _read_complex_orders(self):
        complex_orders_colnames = ['COMPLEX_ID', 'ZONE_ID', 'TYPE', 'FIXED_TERM', 'VARIABLE_TERM', 'RAMP_UP',
                                   'RAMP_DOWN', 'SCHEDULED_STOP_PERIODS']
        complex_orders_cols = dict(zip(complex_orders_colnames, range(len(complex_orders_colnames))))
        self.curs.execute('select %s from COMPLEXORDERS where day_id = %d order by COMPLEX_ID' % (
            ', '.join(complex_orders_colnames), self.day_id))
        complex_orders = self.curs.fetchall()

        self.curs.execute(
            'select COMPLEX_ID, PERIOD, QUANTITY, PRICE from COMPLEXORDER_DATA where day_id = %d order by COMPLEX_ID, PERIOD, POSITION' % self.day_id)
        all_complex_points = self.curs.fetchall()
        if len(all_complex_points) == 0:
            return []

        cur_point = all_complex_points.pop(0)

        # For each complex order, create the curves for each period and append it to the
        orders = []
        for co in complex_orders:
            complex_id = co[complex_orders_cols['COMPLEX_ID']]
            location = co[complex_orders_cols['ZONE_ID']]
            type = co[complex_orders_cols['TYPE']]
            list_of_curves = [(p, location, p, type) for p in range(1,
                                                                    self.n_periods + 1)]  # Create artificial curves so that period replaces the curve_id

            complex_points = []
            while cur_point[0] == complex_id:
                complex_points.append(cur_point[1:])  # Remove complex_id, keep only period, quantity and price
                if len(all_complex_points) > 0:
                    cur_point = all_complex_points.pop(0)
                else:
                    break

            curves = self._create_curves(list_of_curves, complex_points)

            orders.append(ComplexOrder(complex_id,
                                       dict(zip(range(1, self.n_periods + 1), curves)),
                                       FT=co[complex_orders_cols['FIXED_TERM']] if options.APPLY_MIC else 0,
                                       VT=co[complex_orders_cols['VARIABLE_TERM']] if options.APPLY_MIC else 0,
                                       LG_down=co[complex_orders_cols['RAMP_DOWN']],
                                       LG_up=co[complex_orders_cols['RAMP_UP']],
                                       SSperiods=co[complex_orders_cols[
                                           'SCHEDULED_STOP_PERIODS']] if options.APPLY_SCHEDULED_STOP else 0,
                                       location=location))
        return orders

    def _read_PUN_orders(self):
        pun_orders_colnames = ['PUN_ID', 'ZONE_ID', 'PERIOD', 'MERIT_ORDER', 'VOLUME', 'PRICE']
        pun_orders_cols = dict(zip(pun_orders_colnames, range(len(pun_orders_colnames))))
        self.curs.execute('select %s from PUNORDERS where day_id = %d order by ZONE_ID, PRICE DESC' % (
            ', '.join(pun_orders_colnames), self.day_id))
        pun_orders = self.curs.fetchall()

        return [PunOrder(id=po[pun_orders_cols['PUN_ID']],
                         location=po[pun_orders_cols['ZONE_ID']],
                         period=po[pun_orders_cols['PERIOD']],
                         merit_order=po[pun_orders_cols['MERIT_ORDER']],
                         volume=po[pun_orders_cols['VOLUME']],
                         price=po[pun_orders_cols['PRICE']]) for po in pun_orders]

    def _read_lines(self):
        if options.NO_EXCHANGE_CAPACITY:
            return []

        lines_colnames = ['LINE_ID', 'ZONE_FROM', 'ZONE_TO']
        lines_cols = dict(zip(lines_colnames, range(len(lines_colnames))))
        self.curs.execute(
            'select %s from LINES where day_id = %d order by LINE_ID' % (', '.join(lines_colnames), self.day_id))
        lines = self.curs.fetchall()

        line_data_colnames = ['LINE_ID', 'PERIOD', 'CAPACITY_UP', 'CAPACITY_DOWN']
        line_data_cols = dict(zip(line_data_colnames, range(len(line_data_colnames))))
        self.curs.execute('select %s from LINE_DATA where day_id = %d order by LINE_ID, PERIOD' % (
            ', '.join(line_data_colnames), self.day_id))
        line_data = self.curs.fetchall()

        # Generate two lists (one per direction) containing line capacities for all the periods and append
        # it to the line information
        all_lines = []
        if lines:
            lc = line_data.pop(0)
            for l in lines:
                c_up = {}
                c_down = {}
                while lc[0] == l[0]:  # same line id
                    c_up[lc[1]] = lc[2]
                    c_down[lc[1]] = lc[3]
                    if len(line_data) > 0:
                        lc = line_data.pop(0)
                    else:
                        break

                all_lines.append(Line(l[0], l[1], l[2], c_up, c_down))

        return all_lines

    def _read_block_orders(self):

        # Get block volumes
        TABLE = 'BLOCK_DATA'
        block_data_colnames = get_col_names(TABLE)
        block_data_cols = dict(zip(block_data_colnames, range(len(block_data_colnames))))
        self.curs.execute('select %s from %s where day_id = %d order by BLOCK_ID, PERIOD' % (
            ', '.join(block_data_colnames), TABLE, self.day_id))
        block_data = self.curs.fetchall()

        block_volumes = dict()
        for b in block_data:
            block_id = b[block_data_cols['BLOCK_ID']]
            if block_id not in block_volumes.keys():
                block_volumes[block_id] = {}

            block_volumes[block_id][b[block_data_cols['PERIOD']]] = b[block_data_cols['QUANTITY']]

        # Create blocks
        all_blocks = []
        TABLE = 'BLOCKS'
        blocks_colnames = get_col_names(TABLE)
        blocks_cols = dict(zip(blocks_colnames, range(len(blocks_colnames))))
        blocks_query = 'select %s from %s where day_id = %d order by BLOCK_ID'
        self.curs.execute(blocks_query % (', '.join(blocks_colnames), TABLE, self.day_id))
        blocks = self.curs.fetchall()

        for block in blocks:
            block_id = block[blocks_cols['BLOCK_ID']]
            all_blocks.append(BlockBid(block_id,
                                       volumes=block_volumes[block_id],
                                       price=block[blocks_cols['PRICE']],
                                       location=block[blocks_cols['ZONE_ID']],
                                       min_acceptance_ratio=block[blocks_cols['MIN_RATIO']]))

        return all_blocks
