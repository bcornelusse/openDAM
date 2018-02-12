#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sqlite3
from argparse import ArgumentParser

from lxml import etree
import zipfile
import os
import pandas as pd

from openDAM.dataio.create_dam_db_from_csv import create_tables, insert_in_table

PUN_ZONES = ("NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD")
COUPLING_ZONES = ("XFRA", "XAUS", "BSP")
MAXIMUM_PRICE = 3000.0
MINIMUM_PRICE = 0.0


class OrdersList:
    def __init__(self):
        self.zones = set()
        self.periods = set()
        self.orders = {}
        self.last_id_given = 0

    def add(self, order):
        order.id = self.get_next_available_id()

        if order.zone not in self.orders:
            self.orders[order.zone] = {}
            self.zones.add(order.zone)
        if order.period not in self.orders[order.zone]:
            self.orders[order.zone][order.period] = [order]
            self.periods.add(order.period)
        else:
            self.orders[order.zone][order.period].append(order)

        return order.id

    def get_next_available_id(self):
        self.last_id_given += 1
        return self.last_id_given


class Order:
    def __init__(self):
        self.order_type = u'DEMAND'
        self.id = 0
        self.period = 0
        self.price = 0.0
        self.volume = 0.0
        self.zone = u''
        self.merit_order = None
        self.accepted = None

    def __str__(self):
        return u'%s, %d, %.3f, %.3f, %d' % (
            self.zone, self.period, self.volume, self.price, self.merit_order)


class GMEImporter:
    def __init__(self, path, date):
        """

        :param path: Path to directory containing raw data files
        :param date: Date of the day to import
        """
        self.path = path
        self.date = date

        # Determine zones, connections between zones, and transmission limits
        self.all_periods = set()
        self.all_zones = set()
        self.connections = {}
        self.connection_data = {}
        self.read_network_data()

        # Read bids, create pun orders, demand and supply curves
        self.demand_orders = OrdersList()
        self.pun_orders = OrdersList()
        self.awarded_pun_quantities = pd.DataFrame(columns=["DAY_ID", "PERIOD", "PUN_ID", "AWARDED_QUANTITY"])
        self.supply_orders = OrdersList()
        self.read_bids()
        self.read_cross_border_exchanges()  # Actually creates bids in COUPLING_ZONES
        self.all_periods = self.all_periods.union(self.merge_bid_periods())
        self.all_zones = self.all_zones.union(self.merge_bid_zones())

        # Assign a unique ID to each zone.
        self.zone_id = dict(zip(self.all_zones, range(1, len(self.all_zones) + 1)))

        # Prices
        self.real_prices = self.read_prices()

    def merge_bid_periods(self):
        periods = set()
        periods = periods.union(self.demand_orders.periods)
        periods = periods.union(self.pun_orders.periods)
        periods = periods.union(self.supply_orders.periods)
        return periods

    def merge_bid_zones(self):
        zones = set()
        zones = zones.union(self.demand_orders.zones)
        zones = zones.union(self.pun_orders.zones)
        zones = zones.union(self.supply_orders.zones)
        return zones

    def read_bids(self):
        """
        Read bids contained in file yyyymmddMGPOffertePubbliche.xml and dispatch by type (PUN, demand, supply)

        """


        # Unzip
        zip_file_path = self.path + u'/%sMGPOffertePubbliche.zip' % self.date
        zip_ref = zipfile.ZipFile(zip_file_path, 'r')
        zip_ref.extractall(self.path)
        zip_ref.close()

        # Parse
        xml_file_path = self.path + u'/%sMGPOffertePubbliche.xml' % self.date
        tree = etree.parse(xml_file_path)

        for order in tree.xpath(u'/NewDataSet/OfferteOperatori'):

            if order.find(u'STATUS_CD').text in ("INC", "REP", "REV"):
                continue

            o = Order()
            o.order_type = u'DEMAND' if order.find(u'PURPOSE_CD').text == u'BID' else u'SUPPLY'
            o.period = int(order.find(u'INTERVAL_NO').text)
            o.price = float(order.find(u'ENERGY_PRICE_NO').text)
            o.volume = float(order.find(u'ADJ_QUANTITY_NO').text)
            o.zone = order.find(u'ZONE_CD').text
            o.merit_order = int(order.find(u'MERIT_ORDER_NO').text)
            o.accepted = (order.find(u'STATUS_CD').text == u'ACC')
            name = order.find(u'UNIT_REFERENCE_NO').text

            if o.order_type == u'DEMAND':
                if o.price == 0.0 and o.accepted:
                    o.price = MAXIMUM_PRICE

                if o.zone in PUN_ZONES and not name.startswith(u'UP_'):
                    o.order_type = u'PUN'

            if o.order_type == u'DEMAND':
                self.demand_orders.add(o)
            elif o.order_type == u'PUN':
                last_pun_id = self.pun_orders.add(o)
                q = float(order.find(u'AWARDED_QUANTITY_NO').text)
                self.awarded_pun_quantities = self.awarded_pun_quantities.append(dict(DAY_ID=self.date,
                                                                                      PERIOD=o.period,
                                                                                      PUN_ID=last_pun_id,
                                                                                      AWARDED_QUANTITY=q),
                                                                                 ignore_index=True)
            elif o.order_type == u'SUPPLY':
                self.supply_orders.add(o)
            else:
                raise ("Order %s cannot be affected to an OrdersList of a known type" % o)

        # Delete unzipped xml
        del tree
        os.remove(xml_file_path)
        print("Done for bids")

    def read_network_data(self):
        line_id = 1
        connections = {}
        connection_data = {}
        tree = etree.parse(self.path + u'/%sMGPLimitiTransito.xml' % self.date)
        for l in tree.xpath(u'/NewDataSet/LimitiTransito'):
            period = int(l.find(u'Ora').text)
            self.all_periods.add(period)
            from_zone = l.find(u'Da').text
            to_zone = l.find(u'A').text
            self.all_zones.add(from_zone)
            self.all_zones.add(to_zone)
            limit = float(l.find(u'Limite').text.replace(u',', u'.'))

            if (from_zone, to_zone) in connections:  # Capacity up
                lid = connections[(from_zone, to_zone)]
                if period in connection_data[lid]:
                    connection_data[lid][period][1] = limit
                else:
                    connection_data[lid][period] = [0.0, limit]
            elif (to_zone, from_zone) in connections:  # Capacity down
                lid = connections[(to_zone, from_zone)]
                if period in connection_data[lid]:
                    connection_data[lid][period][0] = limit
                else:
                    connection_data[lid][period] = [limit, 0.0]
            else:
                # First time a connection between these two zones is seen,
                # create one in that direction (arbitrary)
                connections[(from_zone, to_zone)] = line_id
                connection_data[line_id] = {}
                connection_data[line_id][period] = [0, limit]
                line_id += 1

        self.connections = {v: k for (k, v) in connections.iteritems()}
        self.connection_data = connection_data

        print(u'Done reading lines')

    def read_cross_border_exchanges(self):
        tree = etree.parse(self.path + u'/%sMGPQuantita.xml' % self.date)
        for l in tree.xpath(u'/NewDataSet/Quantita'):
            for zone in COUPLING_ZONES:
                period = int(l.find("Ora").text)
                demand = float(l.find("%s_ACQUISTI" % zone).text.replace(',', '.'))
                supply = float(l.find("%s_VENDITE" % zone).text.replace(',', '.'))

                demand_order = Order()
                demand_order.period = period
                demand_order.zone = zone
                demand_order.volume = demand
                demand_order.price = MAXIMUM_PRICE
                demand_order.order_type = u'DEMAND'
                self.demand_orders.add(demand_order)

                supply_order = Order()
                supply_order.period = period
                supply_order.zone = zone
                supply_order.volume = supply
                supply_order.price = MINIMUM_PRICE
                supply_order.order_type = u'SUPPLY'
                self.supply_orders.add(supply_order)

        print(u'Done reading cross border exchanges')

    def read_prices(self):
        all_zones_plus_PUN = list(self.all_zones)
        all_zones_plus_PUN.extend([u'PUN', u'NAT'])

        prices = pd.DataFrame(columns=["DAY_ID", "Period"] + all_zones_plus_PUN)
        tree = etree.parse(self.path + u'/%sMGPPrezzi.xml' % self.date)
        for l in tree.xpath(u'/NewDataSet/Prezzi'):
            zone_price = dict(Period=int(l.find("Ora").text), DAY_ID=self.date)
            for zone in all_zones_plus_PUN:
                price = float(l.find(zone).text.replace(u',', u'.'))
                zone_price[zone] = price
            prices = prices.append(zone_price, ignore_index=True)

        print("Done reading and exporting price results")
        return prices

    def to_sql(self, conn, split_by_period=False):
        """
        
        :param conn: a database connection.
        :param split_by_period: if True, generate a day_id by period instead one single day_id and n_periods periods
        :return:
        """

        # DAYS
        table = u'DAYS'
        print("%s to sql" % table)
        data = []
        if split_by_period:
            for period in self.all_periods:
                day_id = self.pun_decomposition_day_id(period)
                n_periods = 1
                data.append([day_id, n_periods])
        else:
            day_id = int(self.date)
            n_periods = len(self.all_periods)
            data.append([day_id, n_periods])

        insert_in_table(conn, table, data)
        conn.commit()

        # ZONES
        table = u'ZONES'
        print("%s to sql" % table)
        data = []
        for zone_name in self.all_zones:
            zone_id = self.zone_id[zone_name]
            if split_by_period:
                for period in self.all_periods:
                    day_id = self.pun_decomposition_day_id(period)
                    data.append([day_id, zone_id, zone_name, MINIMUM_PRICE, MAXIMUM_PRICE])
            else:
                day_id = int(self.date)
                data.append([day_id, zone_id, zone_name, MINIMUM_PRICE, MAXIMUM_PRICE])

        insert_in_table(conn, table, data)
        conn.commit()

        # LINES
        table = u'LINES'
        print("%s to sql" % table)
        data = []
        for connection_id, value in self.connections.iteritems():
            id_from_zone = self.zone_id[value[0]]
            id_to_zone = self.zone_id[value[1]]
            if split_by_period:
                for period in self.all_periods:
                    day_id = self.pun_decomposition_day_id(period)
                    data.append([day_id, connection_id, id_from_zone, id_to_zone])
            else:
                day_id = int(self.date)
                data.append([day_id, connection_id, id_from_zone, id_to_zone])

        insert_in_table(conn, table, data)
        conn.commit()

        #  LINE_DATA
        table = u'LINE_DATA'
        print("%s to sql" % table)
        data = []

        for connection_id, periods in self.connection_data.iteritems():
            for period, capacities in periods.iteritems():
                if split_by_period:
                    day_id = self.pun_decomposition_day_id(period)
                    data.append([day_id, connection_id, 1, capacities[0], capacities[1]])
                else:
                    day_id = int(self.date)
                    data.append([day_id, connection_id, period, capacities[0], capacities[1]])

        insert_in_table(conn, table, data)
        conn.commit()

        # PUN_ORDERS
        table = u'PUNORDERS'
        print("%s to sql" % table)

        for zone in PUN_ZONES:
            data = []
            for period in self.all_periods:
                for o in self.pun_orders.orders[zone][period]:
                    if split_by_period:
                        day_id = self.pun_decomposition_day_id(period)
                        data.append([day_id, o.id, self.zone_id[zone], 1, o.merit_order, o.volume, o.price])
                    else:
                        day_id = int(self.date)
                        data.append([day_id, o.id, self.zone_id[zone], period, o.merit_order, o.volume, o.price])

            insert_in_table(conn, table, data)
            conn.commit()

        # CURVES
        print("Curves and curve data to sql")

        # DEMAND
        curve_id = 0
        for zone in self.all_zones:
            curves = []
            curve_data = []
            demandeOrders = self.demand_orders.orders
            if zone not in demandeOrders:
                continue
            for period in demandeOrders[zone]:
                curve_id += 1
                day_id = self.pun_decomposition_day_id(period) if split_by_period else int(self.date)
                sql_period = 1 if split_by_period else period
                curves.append([day_id, curve_id, self.zone_id[zone], sql_period, u'DEMAND'])
                volume = 0
                position = 0
                for o in sorted(demandeOrders[zone][period], key=lambda x: -x.price):
                    position += 1
                    curve_data.append([day_id, curve_id, position, volume, o.price])
                    position += 1
                    volume += o.volume
                    curve_data.append([day_id, curve_id, position, volume, o.price])

            insert_in_table(conn, u'CURVES', curves)
            insert_in_table(conn, u'CURVE_DATA', curve_data)
            conn.commit()

        # SUPPLY
        for zone in self.all_zones:
            curves = []
            curve_data = []
            supply_orders = self.supply_orders.orders
            if zone not in supply_orders:
                continue
            for period in supply_orders[zone]:
                curve_id += 1
                day_id = self.pun_decomposition_day_id(period) if split_by_period else int(self.date)
                sql_period = 1 if split_by_period else period
                curves.append([day_id, curve_id, self.zone_id[zone], sql_period, u'SUPPLY'])
                volume = 0
                position = 0
                for o in sorted(supply_orders[zone][period], key=lambda x: x.price):
                    position += 1
                    curve_data.append([day_id, curve_id, position, volume, o.price])
                    position += 1
                    volume += o.volume
                    curve_data.append([day_id, curve_id, position, volume, o.price])

            insert_in_table(conn, u'CURVES', curves)
            insert_in_table(conn, u'CURVE_DATA', curve_data)
            conn.commit()

        # Realized prices
        self.real_prices.to_sql("REAL_PRICES", conn, if_exists="append")

        # Realized PUN quantities
        self.awarded_pun_quantities.to_sql("AWARDED_PUN", conn, if_exists="append", index=False)

    def pun_decomposition_day_id(self, period):
        """
        Generates a day_id based on the date seen as an int and the period in {1, ..., 24}

        :param period: an integer
        :return: a day_id
        """
        return int(self.date) * 100 + period


if __name__ == "__main__":

    parser = ArgumentParser(description='Utility for importing GME data.')
    parser.add_argument("-p", "--path", help="Folder where data is located", default='data')
    parser.add_argument("-d", "--database",
                        help="Name of the sqlite database file, under the folder of the --path argument.",
                        default='pun_daily.sqlite3')
    parser.add_argument("--from_date",
                        help="Date of first day to import, as YYYYMMDD, cast as an int.",
                        default='20180101', required=True)
    parser.add_argument("--to_date",
                        help="Date of last day to import, as YYYYMMDD, cast as an int.",
                        default='20180110', required=True)
    parser.add_argument("--append",
                        help="Append to existing database",
                        default=False)

    args = parser.parse_args()

    path = args.path
    database_name = args.database

    if args.append and database_name in os.listdir('.'):
        os.remove(database_name)

    conn = sqlite3.connect(database_name)

    if args.append:
        create_tables(conn)

    for date in range(int(args.from_date), int(args.to_date)+1):
        date_str = str(date)
        print("Importing PUN data for day %s " % date_str)
        importer = GMEImporter(path, date_str)
        importer.to_sql(conn, split_by_period=False)

    conn.close()
