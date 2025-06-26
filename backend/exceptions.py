class RasterCalcError(Exception):
    pass


class LayerNotFoundError(RasterCalcError):
    pass


class InvalidExpressionError(RasterCalcError):
    pass


class RasterSaveError(RasterCalcError):
    pass


class RasterToolsUnavailableError(RasterCalcError):
    pass


class BandMismatchError(RasterCalcError):
    pass


class RasterExtentError(RasterCalcError):
    pass
