# Mock for database access; use sqlite3 in memory rather than MySQL

import sqlite3


class MockCursor:
    def __init__(self, conn):
        self.sql, self.db = conn.sql, conn.db
        self.dbcursor = self.db.cursor()

    def execute(self, statement, args=()):
        self.sql.append(statement)
        # sqlite uses ? as a placeholder; MySQL uses %s
        self.dbcursor.execute(statement.replace('%s', '?'), args)

    def fetchone(self):
        return self.dbcursor.fetchone()

    def __iter__(self):
        fa = self.dbcursor.fetchall()
        return fa.__iter__()


class DictCursor(MockCursor):
    def __init__(self, conn):
        self._oldrf = conn.db.row_factory
        conn.db.row_factory = sqlite3.Row
        super(DictCursor, self).__init__(conn)

    def __del__(self):
        if hasattr(self, 'db'):
            self.db.row_factory = self._oldrf


class MockConnection:
    def __init__(self, db, *args, **keys):
        self.args = args
        self.keys = keys
        self.db = sqlite3.connect(":memory:")
        self.sql = []

    def cursor(self):
        return MockCursor(self)

    def close(self):
        self.db.close()


def connect(*args, **keys):
    return MockConnection(*args, **keys)


# Mock for 'MySQLdb.cursors.DictCursor'
class cursors(object):
    pass


cursors.DictCursor = DictCursor
