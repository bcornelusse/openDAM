=============
Documentation
=============

`Read the doc <http://openDAM.readthedocs.io/en/latest/>`__ for more information.

Alternatively you can generate the documentation yourself if you have sphinx installed:

::

    cd <to the root of the project>
    sphinx-apidoc -o doc/ openDAM/ -f --separate
    cd doc; make html; cd ..

The html doc is in ``_build/html``

============
Installation
============

1. Download the code from `Github <https://github.com/bcornelusse/openDAM>`__
2. We highly recommend to use an Anaconda distribution

 a. download and install `Anaconda <https://www.anaconda.com/download/>`__ for Python 2.7 and your specific OS.

 b. Create one environement for this project

 ::

    conda create --name python_DAM --file conda-{platform}.txt

 where "{platform}" must match your OS. Checkout `this
 reference <https://conda.io/docs/user-guide/tasks/manage-environments.html>`__
 for more information about how to manage Anaconda environments.

 c. Activate the environment

 For Windows:

 ::

    activate python_DAM

 For OSX and Linux,

 ::

    source activate python_DAM

The code is currently tuned for CPLEX.

=======================
Running the application
=======================

1. First, run ``create_dam_db_from_csv.py`` from ``openDAM/dataio/`` to generate an sqlite database, taking as default source scripts the CSV files in folder data/tests. The resulting sqlite database can be browsed using any client for Sqlite.

   * You can modify the call to ``create_dam_db_from_csv.py`` if you want to use other input CSV files.

2. Run ``python openDAM`` from the master directory with either the ``--all`` option, or another option if you want to run a particular day.

========
GME Data
========

The Italian market data can be freely downloaded from the website of the Italian market operator.
The raw data required to run the model is stored in 4 different XML files, named:

1. YYYYMMDDMGPOffertePubbliche.xml, located in a zip file named YYYYMMDDMGPOffertePubbliche.zip, contained in another zip file named YYYYMMDDOfferteFree_Pubbliche.zip. The xml file contains the real market order data;
2. YYYYMMDDMGPLimitiTransito.xml, containing the network capacity limits;
3. YYYYMMDDMGPPrezzi.xml , containing the official prices used for comparison;
4. YYYYMMDDMGPQuantita, containing the flows coming from the non-GME zones;

where YYYYMMDD is the date of the requested day in the format: year, month and day.
These files can be freely downloaded from the following links, for example for January 27th, 2018:

1. https://www.mercatoelettrico.org/en/Download/DownloadDati.aspx?val=OfferteFree_Pubbliche
2. https://www.mercatoelettrico.org/It/WebServerDataStore/MGP_LimitiTransito/20180127MGPLimitiTransito.xml
3. https://www.mercatoelettrico.org/It/WebServerDataStore/MGP_Prezzi/20180127MGPPrezzi.xml
4. https://www.mercatoelettrico.org/It/WebServerDataStore/MGP_Quantita/20180127MGPQuantita.xml

Then, they can be imported into a suitable SQL database by running the Python script GME_xml_importer.py.

Assuming your data is in the folder ``data``, you can do this by running ``python openDAM/dataio/GME_xml_importer.py --split -p data/ -d test.sqlite3 --from_date=20180110 --to_date=20180110``.
The ``--split`` option generates a problem per period.

Then you can run from the master directory
``python openDAM -p openDAM\dataio -d test.sqlite3 -c 2018011019 --pun_strategy=Advanced``

See also ``GME_xml_importer.py --help`` for further details.

==============================
Generating random block orders
==============================

Random block orders can be added to a database by running ``python openDAM/dataio/generate_block_orders.py``.
Parameters defining block properties must be modified directly inside this file (they are not accessible through command line arguments).
