"""Errors we anticipated and can explain.

Most failures in this codebase are not bugs — a login expires, a file is
missing, a provider is unconfigured. Those deserve a sentence and a next step,
not forty lines of third-party stack frames. Raising `FitError` marks a failure
as one the CLI should render that way; everything else keeps the generic
"something unexpected happened, here's the log" treatment.

The message and the hint stay separate on purpose. Folding them into one
string is how you end up with `Sync failed: Garmin auth probe failed:
Authentication failed: API Error 401 - . Run \\`fit auth login\\`...` — each layer
prepending its own context until the only useful words are at the far end.

Subclasses `RuntimeError` so existing callers that catch `RuntimeError` from
`fit.garmin` keep working unchanged.
"""


class FitError(RuntimeError):
    """A failure with a human explanation and, usually, a way out.

    Args:
        message: One sentence saying what went wrong, in the user's terms.
        hint: The next thing to do about it, if there is one.
    """

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class ConfigError(FitError, ValueError):
    """A config value is missing or malformed.

    Also a `ValueError` because config resolution has raised one since it was
    written and callers catch it that way; being a `FitError` too is what earns
    it the clean CLI rendering.
    """


class GarminAuthError(FitError):
    """Garmin will not accept the saved credentials.

    Distinct from a network or infrastructure failure, because the remedy
    differs: re-authenticate versus wait and retry. Telling someone to redo a
    full login with an MFA prompt because of a DNS blip is the wrong
    instruction, so `fit.garmin` only raises this for genuine auth rejections.
    """
