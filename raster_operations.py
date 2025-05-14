import os
import numpy as np
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsMapLayerType,
    QgsCoordinateReferenceSystem,
)
from qgis.utils import iface


def get_loaded_raster_layers():
    """
    Retrieve all loaded raster layers from the current QGIS project.

    Returns:
        list[QgsRasterLayer]: A list of QgsRasterLayer objects.
    """
    return [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if isinstance(layer, QgsRasterLayer)
    ]
