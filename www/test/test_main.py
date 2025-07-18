import utils

utils.set_search_paths(__file__)
import results  # noqa: E402


def test_summary():
    """Test the summary page"""
    c = results.app.test_client()
    _ = c.get('/')
