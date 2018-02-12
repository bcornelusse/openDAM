from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import os

plt.style.use('bmh')
FONT_SIZE = 9


class BidPlotter:
    def __init__(self, dam, path, case):
        self.dam = dam
        self.case_ = case

        self.plots_folder = "%s/plots_%s_%s" % (
            path, case, datetime.now().strftime('%Y%m%d_%H%M%S'))
        if not os.path.isdir(self.plots_folder):
            os.mkdir(self.plots_folder)

    def plot(self, locations=None):
        if locations is None:
            locations = self.dam.zones.keys()

        n_subplots = len(locations)

        fig = plt.figure(1, figsize=(8, 5 * n_subplots))

        curves = self.dam.curves
        pun_orders = self.dam.punOrders

        l = 1
        for location in locations:
            ax1 = plt.subplot(n_subplots, 1, l)

            # plot PUN
            pun_curve = []
            last_volume = 0.0
            for po in pun_orders:
                if po.location == location:
                    pun_curve.append((last_volume, po.price))
                    pun_curve.append((last_volume + po.volume, po.price))
                    last_volume += po.volume
            pun_curve.append((last_volume, 0.0))
            ax1.plot([x[0] for x in pun_curve], [x[1] for x in pun_curve], label="PUN curve")
            maxPrice = pun_curve[0][1]

            # Plot supply
            supply_curve_points = []
            last_volume = 0.0
            for curve in curves:
                if curve.location == location:
                    for bid in curve.bids:
                        if bid.volume > 0:  # Supply
                            supply_curve_points.append((last_volume, bid.price))
                            supply_curve_points.append((last_volume + bid.volume, bid.price))
                            last_volume += bid.volume
            if supply_curve_points:
                maxPrice = max(maxPrice, supply_curve_points[-1][1])
                supply_curve_points.append((last_volume, maxPrice))
                ax1.plot([x[0] for x in supply_curve_points], [x[1] for x in supply_curve_points],
                         label="Supply")

            # Plot demand
            demand_curve_points = []
            last_volume = 0.0
            for curve in curves:
                if curve.location == location:
                    for bid in curve.bids:
                        if bid.volume < 0:  # Demand
                            demand_curve_points.append((last_volume, bid.price))
                            last_volume -= bid.volume
                            demand_curve_points.append((last_volume, bid.price))
            if demand_curve_points:
                demand_curve_points.append((last_volume, 0))
                ax1.plot([x[0] for x in demand_curve_points], [x[1] for x in demand_curve_points],
                         label="Demand")

            ax1.legend(fontsize=FONT_SIZE)
            ax1.set_xlabel('MWh', fontsize=FONT_SIZE)
            ax1.set_ylabel('EUR/MWh', fontsize=FONT_SIZE)

            ax1.set_title("Zone %d" % l)

            l += 1

        fig.savefig("%s/bids.pdf" % self.plots_folder)
