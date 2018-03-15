import logging
import time
import os
import errno

from openDAM.model.complex_order_model import COMPLEX_DAM
from openDAM.model.pun_dam_model import PUN_DAM


class CSV_writer:

    def __init__(self, output_path):
        """

        :param output_path:
        :param pun: PUN model or not PUN model
        """

        self.path = output_path+'/results'+time.strftime("%Y%m%d_%H%M")
        try:
            os.makedirs(self.path)
        except OSError as exception:
            if exception.errno != errno.EEXIST:
                raise

        self.welfare = None
        self.prices = None
        self.line = None
        self.complex = None
        self.pun = None

        self._open_files('w')
        self.write_headers()
        self.close_files()

    def _open_files(self, status='w'):
        self.welfare = open('%s/welfare_PD.csv' % self.path, status)
        self.prices = open('%s/prices_PD.csv' % self.path, status)
        self.line = open('%s/line_results_PD.csv' % self.path, status)
        self.complex = open('%s/complex_results_PD.csv' % self.path, status)
        self.block = open('%s/block_results_PD.csv' % self.path, status)
        self.pun = open('%s/pun_results_PD.csv' % self.path, status)

    def write_headers(self):
        self.welfare.write('DAY_ID,WELFARE,TIME,NBIN,EXPANSION,ABSOLUTE_GAP\n')
        self.prices.write('DAY_ID,ZONE_ID,ZONE_NAME,PERIOD,PRICE,MATCHED_SUPPLY_VOLUME,MATCHED_DEMAND_VOLUME\n')
        self.line.write('DAY_ID,LINE_ID, descritption, direction, value\n')
        self.complex.write('DAY_ID,COMPLEX_ID,ACCEPT,SURPLUS,\n')
        self.block.write('DAY_ID,BLOCK_ID,ACCEPT,SURPLUS,\n')
        self.pun.write('DAY_ID,PUN_ID,ACCEPT\n')

    def update(self, dam):

        self._open_files('a')
        day = dam.day_id
        logging.info('Updating results for day %d' % day)

        if not hasattr(dam, "solver_message"):
            self.welfare.write('%d,%f,%.2f,%d,%d, %.2f\n' % (day, dam.welfare, dam.t_solve, dam.nbinvar, dam.expansion, dam.absolute_gap))
        else:
            self.welfare.write('%d,%f,%.2f,%d,%d, %s\n' % (day, dam.welfare, dam.t_solve, dam.nbinvar, dam.expansion, dam.solver_message))

        # WRITE price results
        all_zones = dam.zones.keys()
        for zone in all_zones:
            p = dam.prices(zone)
            v_s = dam.volumes("SUPPLY", zone)
            v_d = dam.volumes("DEMAND", zone)
            for period in sorted(p.keys()):
                self.prices.write('%d,%d,%s,%d,%.6f,%.3f,%.3f\n' % (day, zone, dam.zones[zone].name, period, p[period], v_s[period], v_d[period]))

        if isinstance(dam, PUN_DAM):
            zone = 0
            p = dam.prices(zone)
            for period in sorted(p.keys()):
                tot_pun_q = sum(
                    dam.orders.bids[b].volume*dam.orders.bids[b].acceptance
                    for b in dam.model.punBids if (dam.orders.bids[b].period == period))
                self.prices.write('%d,%d,%s,%d,%.6f,%.3f,%.3f\n' % (day, 0, "PUN", period, p[period], 0, -tot_pun_q))

        # WRITE flows
        for l in dam.connections:
            self.line.write('%d,%d,flow,UP,%s\n' % (day, l.line_id, ','.join([str(v) for v in l.flow_up])))
            self.line.write('%d,%d,flow,DOWN,%s\n' % (day, l.line_id, ','.join([str(v) for v in l.flow_down])))
            self.line.write('%d,%d,shadow,UP,%s\n' % (day, l.line_id, ','.join([str(v) for v in l.congestion_up])))
            self.line.write('%d,%d,shadow,DOWN,%s\n' % (day, l.line_id, ','.join([str(v) for v in l.congestion_down])))

        for b in dam.block_orders:
            V = b.total_volume()
            l = b.location
            P = b.price
            zonal_prices = dam.prices(l)
            surplus = sum([zonal_prices[t] * v for t, v in b.volumes.items()]) - P * V
            self.block.write('%d,%d,%.6f,%.2f\n' % (day, b.id, b.acceptance, surplus))

        # WRITE results related to complex orders
        if isinstance(dam, COMPLEX_DAM):
            for c in dam.complexOrders:
                self.complex.write('%d,%d,%d,%.2f,%s,%s\n' % (day, c.complex_id, round(c.acceptance), c.surplus,
                                                              ','.join([str(v) for v in c.volumes]),
                                                              ','.join([str(v) for v in c.pi_lg])))
        if isinstance(dam, PUN_DAM):
            for p in dam.punOrders:
                self.pun.write(u'%d,%d,%.6f\n' % (day, p.id, p.acceptance*p.volume))

        self.close_files()

    def close_files(self):
        self.welfare.close()
        self.prices.close()
        self.line.close()
        self.complex.close()
        self.pun.close()