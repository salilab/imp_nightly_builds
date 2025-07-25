import datetime
import os
import sys
import flask
import tempfile
import pathlib


DEFAULT_DATE = datetime.date(year=2020, month=1, day=1)


# Make reading flask config a noop
def _mock_from_pyfile(self, fname, silent=False):
    pass


flask.Config.from_pyfile = _mock_from_pyfile


def set_search_paths(fname):
    """Set search paths so that we can import Python modules and use mocks"""
    # Path to mocks
    sys.path.insert(0, os.path.join(os.path.dirname(fname), 'mock'))
    # Path to top level
    sys.path.insert(0, os.path.join(os.path.dirname(fname), '..'))
    # Path to imp_build_utils
    sys.path.insert(0, os.path.join(os.path.dirname(fname), '..', '..'))


def import_mocked():
    import results
    import imp_build_utils

    tempdir = tempfile.TemporaryDirectory()
    del imp_build_utils.topdir
    topdir = imp_build_utils.topdir = pathlib.Path(tempdir.name) / 'topdir'
    date_dir = DEFAULT_DATE.strftime('%Y%m%d')
    (topdir / 'develop' / date_dir).mkdir(parents=True, exist_ok=True)
    (topdir / 'develop' / '.last').symlink_to(date_dir)

    results.app.config.DEBUG = True
    results.app.config.TESTING = True
    results.app.config["HOST"] = 'testhost'
    results.app.config["USER"] = 'testuser'
    results.app.config["PASSWORD"] = 'testpassword'
    results.app.config["DATABASE"] = 'testdatabase'
    return results, tempdir


def set_up_database(db):
    c = db.cursor()
    c.execute('CREATE TABLE imp_test_reporev ( rev VARCHAR(40) NOT NULL, '
              'date DATE NOT NULL PRIMARY KEY )')
    c.execute('INSERT INTO imp_test_reporev (rev, date) VALUES (%s,%s)',
              ('testrev', DEFAULT_DATE))
    c.execute('CREATE TABLE imp_test_other_reporev ( rev VARCHAR(40), '
              'repo TEXT, date DATE)')
    c.execute('INSERT INTO imp_test_other_reporev (rev, repo, date) '
              'VALUES (%s,%s,%s)', ('rmfgithash', 'rmf', DEFAULT_DATE))
    c.execute("CREATE TABLE imp_test_names ( id INT, name VARCHAR(150), "
              "unit INT)")
    c.execute("INSERT INTO imp_test_names (id, name, unit) VALUES (%s,%s,%s)",
              (42, 'em-goodtest', 5))
    c.execute("INSERT INTO imp_test_names (id, name, unit) VALUES (%s,%s,%s)",
              (60, 'em-badtest', 5))
    c.execute("INSERT INTO imp_test_names (id, name, unit) VALUES (%s,%s,%s)",
              (99, 'em-newbadtest', 5))
    c.execute("INSERT INTO imp_test_names (id, name, unit) VALUES (%s,%s,%s)",
              (100, 'em-longtest', 5))
    c.execute("CREATE TABLE imp_test ( name INT, arch INT, state TEXT, "
              "detail TEXT, runtime FLOAT, date DATE, delta TEXT )")
    c.execute("INSERT INTO imp_test (name, arch, state, detail, runtime, "
              "date, delta) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (42, 3, "OK", "", 1.0, DEFAULT_DATE, None))
    c.execute("INSERT INTO imp_test (name, arch, state, detail, runtime, "
              "date, delta) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (60, 3, "FAIL", "", 1.0, DEFAULT_DATE, None))
    c.execute("INSERT INTO imp_test (name, arch, state, detail, runtime, "
              "date, delta) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (99, 3, "FAIL", "", 1.0, DEFAULT_DATE, "NEWFAIL"))
    c.execute("INSERT INTO imp_test (name, arch, state, detail, runtime, "
              "date, delta) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (100, 3, "OK", "", 100.0, DEFAULT_DATE, None))
    c.execute("CREATE TABLE imp_test_archs ( id INT, name VARCHAR(20) )")
    c.execute('INSERT INTO imp_test_archs (id, name) VALUES (%s,%s)',
              (3, 'coverage'))
    c.execute("CREATE TABLE imp_test_units ( id INT, name VARCHAR(40), "
              "lab_only INT )")
    c.execute('INSERT INTO imp_test_units (id, name, lab_only) '
              'VALUES (%s,%s,%s)', (5, 'IMP.em', 0))
    c.execute("CREATE TABLE imp_test_unit_result ( arch INT, unit INT, "
              "state TEXT, logline INT, date DATE )")
    c.execute("CREATE TABLE imp_build_summary ( state TEXT, date DATE, "
              "lab_only INT )")
    c.execute("CREATE TABLE imp_doc ( date DATE, nbroken_tutorial INT, "
              "nbroken_manual INT, nbroken_rmf_manual INT )")
    c.execute("CREATE TABLE imp_benchmark ( name INT, runtime FLOAT, "
              "checkval FLOAT, date DATE, platform INT )")
    c.execute("CREATE TABLE imp_benchmark_files ( id INT, unit INT, "
              "name TEXT )")
    c.execute("CREATE TABLE imp_benchmark_names ( id INT, file INT, "
              "name TEXT, algorithm TEXT )")
    c.execute("INSERT INTO imp_benchmark (name, runtime, checkval, date, "
              "platform) VALUES (%s,%s,%s,%s,%s)",
              (19, 0.5, 99, DEFAULT_DATE, 3))
    c.execute("INSERT INTO imp_benchmark_names (id, file, name, algorithm) "
              "VALUES (%s,%s,%s,%s)", (19, 29, "rmf load", "rmf"))
    c.execute("INSERT INTO imp_benchmark_files (id, unit, name) "
              "VALUES (%s,%s,%s)", (29, 5, "benchmark_load"))
