from qgis.core import QgsProject, QgsRasterLayer
from typing import Optional


class LayerManager:
    def __init__(self):
        self.project = QgsProject.instance()
        self._layer_cache = {}

    def get_raster_layer(self, name: str) -> Optional[QgsRasterLayer]:
        if name in self._layer_cache:
            return self._layer_cache[name]

        layers = self.project.mapLayersByName(name)
        for layer in layers:
            if isinstance(layer, QgsRasterLayer):
                self._layer_cache[name] = layer
                return layer
        return None

    def validate_layer_names(self, layer_names: list[str]) -> list[str]:
        missing_layers = []
        for name in layer_names:
            layer = self.get_raster_layer(name)
            if layer is None:
                missing_layers.append(name)
        return missing_layers
