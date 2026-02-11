"""ADP Hypervisor - Agentic Data Protocol Python Implementation."""

__all__ = ["ADPServer"]

__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    """Lazy import to avoid circular dependency with backends."""
    if name == "ADPServer":
        from adp_hypervisor.server import ADPServer

        return ADPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
