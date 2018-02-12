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

Please refer to the examples 

.. toctree::
  :maxdepth: 2
  
  examples

