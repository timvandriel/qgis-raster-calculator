import raster_tools
from .layer_manager import LayerManager
from typing import Optional
from .exceptions import RasterToolsUnavailableError, LayerNotFoundError


class RasterManager:
    """
    Manages conversion of QGIS raster layers into `raster_tools.Raster` objects.
    Uses a cache to avoid redundant conversions and improves performance.
    """

    def __init__(self, layer_manager: LayerManager):
        """
        Initializes the RasterManager with a reference to the LayerManager.

        Args:
            layer_manager (LayerManager): The manager used to retrieve QGIS raster layers.
        """
        self.layer_manager = layer_manager
        self._raster_cache = {}  # Cache of Raster objects keyed by layer name

    def get_raster(self, name: str) -> Optional[raster_tools.Raster]:
        """
        Retrieves a lazy `raster_tools.Raster` object for a given raster layer name.

        Args:
            name (str): The name of the raster layer to retrieve.

        Returns:
            raster_tools.Raster or None: A `Raster` object if the layer exists; otherwise, None.
        """
        if name in self._raster_cache:
            return self._raster_cache[name]

        # Attempt to retrieve the corresponding QGIS raster layer
        qgis_layer = self.layer_manager.get_raster_layer(name)
        # If the layer is not found, raise an exception
        if not qgis_layer:
            raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")

        try:
            raster = raster_tools.Raster(qgis_layer.source()).astype("float32")
        except Exception as e:
            # Wrap and raise a more informative error if Raster creation fails
            raise RasterToolsUnavailableError(
                f"Failed to create Raster from layer '{name}': {str(e)}"
            )

        self._raster_cache[name] = raster
        return raster

    def get_rasters(self, names: list[str]) -> dict[str, raster_tools.Raster]:
        """
        Retrieves a dictionary of `raster_tools.Raster` objects for a list of layer names.

        Args:
            names (list[str]): List of raster layer names to retrieve.

        Returns:
            dict[str, raster_tools.Raster]: Dictionary mapping names to `Raster` objects.
        """
        rasters = {}
        for name in names:
            raster = self.get_raster(name)
            if raster:
                rasters[name] = raster
            else:
                raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")
        return rasters
