"""Custom exceptions so callers get clear, actionable errors instead of
raw FastF1/pandas tracebacks."""


class SAIF1Error(Exception):
    """Base exception for all SAIF1-specific errors."""


class SessionNotFoundError(SAIF1Error):
    """Raised when a requested session could not be located or loaded."""


class DriverNotFoundError(SAIF1Error):
    """Raised when a requested driver has no data in the loaded session."""


class DataUnavailableError(SAIF1Error):
    """Raised when required timing/session data is missing or empty."""
