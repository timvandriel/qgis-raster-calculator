from raster_tools import Raster
import os
import numpy as np
from qgis.core import QgsProject, QgsRasterLayer, QgsMapLayerType
from qgis.utils import iface


def get_loaded_raster_layers():
    """
    Get all loaded raster layers in the QGIS project.

    Returns:
        list: A list of QgsRasterLayer objects.
    """
    layers = QgsProject.instance().mapLayers().values()
    raster_layers = [
        layer for layer in layers if layer.type() == QgsMapLayerType.RasterLayer
    ]
    return raster_layers
