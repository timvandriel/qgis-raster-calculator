from qgis.core import QgsProject, QgsRasterLayer
from typing import Optional
from .exceptions import LayerNotFoundError


class LayerManager:
    """
    Manages access to raster layers in the current QGIS project,
    including caching for efficiency and validation of layer presence.
    """

    def __init__(self):
        """
        Initializes the LayerManager by referencing the current QGIS project instance
        and preparing a cache for quick layer retrieval.
        """
        self.project = QgsProject.instance()
        self._layer_cache = {}  # Cache to store already looked-up raster layers by name

    def get_raster_layer(self, name: str) -> Optional[QgsRasterLayer]:
        """
        Retrieves a raster layer by name from the current project.

        Args:
            name (str): The name of the raster layer to retrieve.

        Returns:
            QgsRasterLayer or None: The matching raster layer, if found; otherwise, None.
        """
        # Return from cache if available
        if name in self._layer_cache:
            return self._layer_cache[name]

        # Search for raster layers with the given name
        layers = self.project.mapLayersByName(name)
        for layer in layers:
            if isinstance(layer, QgsRasterLayer):
                self._layer_cache[name] = layer  # Cache the result
                return layer

        return None  # No matching raster layer found

    def validate_layer_names(self, layer_names: list[str]) -> None:
        """
        Validates a list of raster layer names, ensuring all are present in the project.

        Args:
            layer_names (list[str]): A list of raster layer names to validate.

        Raises:
            LayerNotFoundError: If any of the specified raster layers are not found.
        """
        missing_layers = []
        for name in layer_names:
            layer = self.get_raster_layer(name)
            if layer is None:
                missing_layers.append(name)

        if missing_layers:
            raise LayerNotFoundError(
                f"Missing raster layers: {', '.join(missing_layers)}"
            )
