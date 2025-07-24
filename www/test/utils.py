import os
import sys
import flask
import tempfile
import pathlib


DEFAULT_DATE = "20200101"


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
    (topdir / 'develop' / DEFAULT_DATE).mkdir(parents=True, exist_ok=True)
    (topdir / 'develop' / '.last').symlink_to(DEFAULT_DATE)

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
    c.execute("CREATE TABLE imp_test ( name INT, arch INT, state TEXT, "
              "detail TEXT, runtime FLOAT, date DATE, delta TEXT )")
    c.execute("CREATE TABLE imp_test_names ( id INT, name VARCHAR(150), "
              "unit INT)")
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
