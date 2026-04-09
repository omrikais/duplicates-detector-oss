try:
    from duplicates_detector._version import __version__
except ModuleNotFoundError:  # not installed / no build hook ran
    __version__ = "0.0.0.dev0+unknown"

__all__ = ["__version__"]
