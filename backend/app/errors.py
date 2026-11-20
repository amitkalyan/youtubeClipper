"""Failures the API can explain without a traceback."""


class ClipperError(Exception):
    """Expected failure with a message safe to show in the UI."""


class FFmpegNotFoundError(ClipperError):
    pass


class InvalidMediaError(ClipperError):
    pass


class AudioTrackMissingError(ClipperError):
    pass


class TranscriptionError(ClipperError):
    pass


class JobBusyError(ClipperError):
    pass


class UploadTooLargeError(ClipperError):
    pass


class CancelledError(ClipperError):
    pass


class NotFoundError(ClipperError):
    pass


class OllamaError(ClipperError):
    pass
