import utils

utils.set_search_paths(__file__)
import results


def test_summary():
    """Test the summary page"""
    c = results.app.test_client()
    _ = c.get('/')
