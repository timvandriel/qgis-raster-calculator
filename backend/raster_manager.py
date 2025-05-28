import raster_tools
from .layer_manager import LayerManager
from typing import Optional, Dict


class RasterManager:
    def __init__(self, layer_manager: LayerManager):
        self.layer_manager = layer_manager
        self._raster_cache = {}

    def get_raster(self, name: str) -> Optional[raster_tools.Raster]:
        if name in self._raster_cache:
            return self._raster_cache[name]

        qgis_layer = self.layer_manager.get_raster_layer(name)
        if not qgis_layer:
            return None
        raster = raster_tools.Raster(qgis_layer.source())
        self._raster_cache[name] = raster
        return raster

    def get_rasters(self, names: list[str]) -> dict[str, raster_tools.Raster]:
        rasters = {}
        for name in names:
            raster = self.get_raster(name)
            if raster:
                rasters[name] = raster
        return rasters
