import sqlite3
from argparse import ArgumentParser

import numpy as np

from openDAM.dataio.create_dam_db_from_csv import insert_in_table, create_tables

PUN_ZONES = {"SICI": 17, "SVIZ": 6}
MIN_RATIO = 0.1
PERIODS = range(9, 21)
N_BLOCKS_PER_ZONE = 25
QUANTITY_RANGE = [1, 75]
MEAN_PRICE = 50
STDEV_PRICE = 10


def populate_block_orders(connection, day_id):
    block_id = 0

    for zone, zone_id in PUN_ZONES.iteritems():
        print("Creating blocks for zone " + zone)

        data = []
        profile_data = []

        for block in range(1, N_BLOCKS_PER_ZONE + 1):
            block_id += 1
            price = np.random.normal(MEAN_PRICE, STDEV_PRICE)
            data.append([day_id, block_id, zone_id, price, MIN_RATIO])

            for period in range(1, 25):
                quantity = 0.0
                if period in PERIODS:
                    quantity = np.random.uniform(QUANTITY_RANGE[0], QUANTITY_RANGE[1])
                profile_data.append([day_id, block_id, period, quantity])

        insert_in_table(connection, "BLOCKS", data)
        insert_in_table(connection, "BLOCK_DATA", profile_data)
        conn.commit()

        print(block_id)


if __name__ == "__main__":
    parser = ArgumentParser(
        description='Utility for Adding randomly generated blocks to a database. Block properties are defined at the top.')
    parser.add_argument("-p", "--path", help="Folder where data is located", required=True)
    parser.add_argument("-d", "--database",
                        help="Name of the sqlite database file, under the folder of the --path argument.", required=True)
    parser.add_argument("--from_date", help="Date of first day to import, as YYYYMMDD, cast as an int.",
                        required=True)
    parser.add_argument("--to_date", help="Date of last day to import, as YYYYMMDD, cast as an int.",
                        required=True)
    parser.add_argument("--create_tables", help="True if block related tables must be created", default=False)
    parser.add_argument("--seed", help="Seed for random number generation", default=1984)

    args = parser.parse_args()

    conn = sqlite3.connect('%s/%s' % (args.path, args.database))

    if args.create_tables:
        create_tables(conn, ["BLOCKS", "BLOCK_DATA"])

    cursor = conn.cursor()
    cmd = "delete from BLOCKS"
    cursor.execute(cmd)

    cmd = "delete from BLOCK_DATA"
    cursor.execute(cmd)

    for date in range(int(args.from_date), int(args.to_date) + 1):
        np.random.seed(int(args.seed))
        populate_block_orders(conn, date)

    conn.close()
