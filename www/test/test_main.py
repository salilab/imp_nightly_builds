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
