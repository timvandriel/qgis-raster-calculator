from qgis.core import QgsProject, QgsRasterLayer
from typing import Optional
from .exceptions import LayerNotFoundError
import re


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

    def get_raster_layer(self, name: str) -> Optional[QgsRasterLayer]:
        """
        Retrieves a raster layer by name from the current QGIS project.

        Args:
            name (str): The layer name, optionally with "@<band>" suffix.

        Returns:
            QgsRasterLayer or None
        """
        # Remove trailing @<number> if present
        match = re.match(r"^(.+?)@(\d+)$", name)
        base_name = match.group(1) if match else name

        # Remove " (Lazy)" if it's part of the display name
        if base_name.endswith(" (Lazy)"):
            base_name = base_name[:-7]

        # Search by cleaned name
        layers = self.project.mapLayersByName(base_name)
        for layer in layers:
            if isinstance(layer, QgsRasterLayer):
                return layer

        return None

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
