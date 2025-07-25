import utils

utils.set_search_paths(__file__)

results, tempdir = utils.import_mocked()


def test_summary():
    """Test the summary page"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        rv = c.get('/')
        assert rv.status_code == 200
        assert b'Summary for build on 2020-01-01' in rv.data


def test_invalid_platform():
    """Test the platform page with an invalid platform ID"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/platform/999', '/?p=platform&plat=999'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'Invalid platform requested' in rv.data


def test_platform():
    """Test the platform page"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/platform/3', '/?p=platform&plat=3'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'Platform: Coverage' in rv.data
            assert b'The build scripts can also be found' in rv.data
            assert b'All log files for this platform<' in rv.data


def test_invalid_component():
    """Test the component page with an invalid component ID"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/comp/999', '/?comp=999'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'Unknown component.' in rv.data


def test_component():
    """Test the component page"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/comp/5', '/?comp=5'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'All IMP.em test results for build' in rv.data
            assert b'Name of the Python or C++ file ' in rv.data


def test_badge():
    """Test the status badge"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/badge.svg', '/?p=stat'):
            rv = c.get(url)
            assert rv.status_code == 302


def test_all_failures():
    """Test display of all failed tests"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/all-fail', '/?p=all'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'All test failures for build on 2020-01-01' in rv.data
            assert b'em-goodtest' not in rv.data
            assert b'em-badtest' in rv.data
            assert b'em-newbadtest' in rv.data
            assert b'em-longtest' not in rv.data


def test_new_failures():
    """Test display of new failed tests"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/new-fail', '/?p=new'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'New test failures for build on 2020-01-01' in rv.data
            assert b'em-goodtest' not in rv.data
            assert b'em-badtest' not in rv.data
            assert b'em-newbadtest' in rv.data
            assert b'em-longtest' not in rv.data


def test_long_tests():
    """Test display of new failed tests"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/long', '/?p=long'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'Long-running tests for build on 2020-01-01' in rv.data
            assert b'em-goodtest' not in rv.data
            assert b'em-badtest' not in rv.data
            assert b'em-newbadtest' not in rv.data
            assert b'em-longtest' in rv.data


def test_platform_component_tests():
    """Test display of tests for a given platform and component"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/platform/3/comp/5', '/?p=compplattest&plat=3&comp=5'):
            rv = c.get(url)
            assert rv.status_code == 200
            assert b'IMP.em test results for build on 2020-01-01' in rv.data
            assert b'Coverage build' in rv.data
            assert b'em-goodtest' in rv.data
            assert b'em-badtest' in rv.data
            assert b'em-newbadtest' in rv.data
            assert b'em-longtest' in rv.data


def test_one_test():
    """Test display of a single test"""
    with results.app.app_context():
        utils.set_up_database(results.get_db())
        c = results.app.test_client()
        for url in ('/platform/3/test/100', '/?p=results&plat=3&test=100'):
            rv = c.get(url)
            assert rv.status_code == 200
            print(rv.data.decode(), file=sys.stderr)
            assert b'Test results, 2020-01-01, develop testrev' in rv.data
            assert b'Previously failed on' in rv.data
            assert b'em-longtest' in rv.data
