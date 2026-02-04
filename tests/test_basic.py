"""Basic tests for adp_server package."""

from adp_server import __version__


def test_version() -> None:
    """Test that version is defined."""
    assert __version__ == "0.1.0"
