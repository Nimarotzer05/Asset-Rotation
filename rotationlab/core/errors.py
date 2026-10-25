"""Exception hierarchy. Every layer raises from here so the CLI can map errors to exit codes."""


class RotationLabError(Exception):
    """Base class."""


class ConfigError(RotationLabError):
    """Invalid or inconsistent configuration."""


class RegistryError(RotationLabError):
    """Duplicate or unknown feature/strategy."""


class DataError(RotationLabError):
    """Provider failure, schema violation, missing series."""


class QualityError(DataError):
    """A blocking quality check failed; no trading decisions may be made on this data."""


class LookaheadError(RotationLabError):
    """A view or feature returned information not knowable at its date."""


class RiskHalt(RotationLabError):
    """Kill switch active: hold positions, make no new trades, alert."""
