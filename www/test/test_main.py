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
        rv = c.get('/platform/999')
        assert rv.status_code == 200
        assert b'Invalid platform requested' in rv.data
