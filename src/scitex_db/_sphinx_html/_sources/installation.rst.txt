Installation
============

Requirements
------------

Python 3.10 or newer with SQLite support is required. Declared runtime
requirements are click>=8.0, numpy, pandas and scitex-logging>=0.2.0.
Dependency build requirements depend on the platform and available wheels.

Basic installation
------------------

.. code-block:: bash

   python -m pip install scitex-db
   python -c "import sqlite3, scitex_db; print(scitex_db.__version__, sqlite3.sqlite_version)"
   scitex-db --version
   scitex-db --help

The standalone namespace is scitex_db and the command is scitex-db.
This distribution does not ship a scitex package or implement scitex.db.
Any separately installed umbrella facade needs its own installed checks.
Import, version and help checks do not establish health, repair or native
PostgreSQL support.

Optional profiles
-----------------

The postgresql extra declares psycopg2-binary and sqlalchemy; its driver
module is psycopg2. Installing it does not create a server or credentials.
The git extra declares GitPython; dev provides test/development tooling and
the PostgreSQL driver for tests; docs provides Sphinx and its extensions.
The all extra references those four extras. pyproject.toml owns the exact
requirements; installed distribution metadata describes a specific environment.

Development
-----------

.. code-block:: bash

   git clone https://github.com/scitex-ai/scitex-db.git
   cd scitex-db
   python -m pip install -e ".[all]"

An editable installation describes the selected checkout. It does not prove
that a public wheel, running service or served documentation has adopted it.
