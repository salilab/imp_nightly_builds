import os
import sys
import flask


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
