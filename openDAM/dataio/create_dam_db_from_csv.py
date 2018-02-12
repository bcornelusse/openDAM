import os
from argparse import ArgumentParser
import pandas
import sqlite3


TABLES = dict(
    BLOCKS='DAY_ID INTEGER, BLOCK_ID INTEGER, ZONE_ID INTEGER, PRICE NUMBER, MIN_RATIO NUMBER',
    BLOCK_DATA='DAY_ID INTEGER, BLOCK_ID INTEGER, PERIOD INTEGER, QUANTITY NUMBER',
    PUNORDERS='DAY_ID INTEGER, PUN_ID INTEGER, ZONE_ID INTEGER, PERIOD INTEGER, MERIT_ORDER INTEGER, VOLUME NUMBER, PRICE NUMBER',
    LINE_DATA='DAY_ID INTEGER, LINE_ID INTEGER, PERIOD INTEGER, CAPACITY_DOWN NUMBER, CAPACITY_UP NUMBER',
    LINES='DAY_ID INTEGER, LINE_ID INTEGER, ZONE_FROM INTEGER, ZONE_TO INTEGER',
    COMPLEXORDER_DATA='DAY_ID INTEGER, COMPLEX_ID INTEGER, PERIOD INTEGER, POSITION INTEGER, QUANTITY NUMBER, PRICE NUMBER',
    COMPLEXORDERS='DAY_ID INTEGER, COMPLEX_ID INTEGER, ZONE_ID INTEGER, TYPE TEXT, FIXED_TERM NUMBER, VARIABLE_TERM NUMBER, RAMP_UP NUMBER, RAMP_DOWN NUMBER, SCHEDULED_STOP_PERIODS INTEGER',
    CURVE_DATA='DAY_ID INTEGER, CURVE_ID INTEGER, POSITION INTEGER, QUANTITY NUMBER, PRICE NUMBER',
    CURVES='DAY_ID INTEGER, CURVE_ID INTEGER, ZONE_ID INTEGER, PERIOD INTEGER, TYPE TEXT',
    ZONES='DAY_ID INTEGER, ZONE_ID INTEGER, NAME TEXT, MINIMUMPRICE NUMBER, MAXIMUMPRICE NUMBER',
    DAYS='DAY_ID INTEGER, NPERIODS INTEGER')


def create_tables(conn):
    """

    :param conn: a connection to the database.
    """
    curs = conn.cursor()

    for table in TABLES.keys():
        curs.execute("CREATE TABLE %s (%s);" % (table, TABLES[table]))


def load_csv_data(conn, path):
    """
    Create table content from input files in CSV format.

    :param conn: a connection to the database.
    :param path: path to the CSV file.
    """

    for table in TABLES.keys():
        print('Processing %s' % table)
        df = pandas.read_csv('%s/%s.csv' % (path, table), index_col="DAY_ID")
        df.to_sql(table, conn, if_exists="append")

def insert_in_table(conn, table_name, data):
    cursor = conn.cursor()

    col_names = get_col_names(table_name)

    for row in data:
        cmd = "INSERT INTO %s (%s) values (%s)" % (table_name, ','.join(col_names), ', '.join('?'*len(col_names)))
        #print(cmd)
        cursor.execute(cmd, row)


def get_col_names(table_name):
    return [col.split(u' ')[0] for col in TABLES[table_name].split(u', ')]


if __name__ == "__main__":
    parser = ArgumentParser(
        description='Utility for day-ahead electricity market clearing algorithm: store CSV files in DB')
    parser.add_argument("-p", "--path", help="Folder where data is located",
                        default='data')
    parser.add_argument("-d", "--database",
                        help="Name of the sqlite database file, under the folder of the --path argument.",
                        default='tests.sqlite3')

    args = parser.parse_args()

    path = args.path
    dbName = args.database

    absolute_db_path = "%s/%s" % (path, dbName)
    if dbName in os.listdir(path):
        os.remove(absolute_db_path)
    conn = sqlite3.connect(absolute_db_path)

    create_tables(conn)
    load_csv_data(conn, path)

    print("DONE")
