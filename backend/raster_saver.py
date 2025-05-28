import os
from qgis.core import QgsProject, QgsRasterLayer, QgsMessageLog, Qgis
from .exceptions import RasterCalcError, RasterSaveError


class RasterSaver:
    def save(self, raster, output_path: str, driver="GTiff"):
        try:
            raster.save(output_path, driver=driver)
            QgsProject.instance().addMapLayer(
                QgsRasterLayer(output_path, os.path.basename(output_path))
            )
            QgsMessageLog.logMessage(
                f"Raster saved to {output_path}", "Lazy Raster Calculator", Qgis.Info
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error saving raster: {str(e)}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise RasterSaveError(str(e))

    def set_crs(self, raster, crs):
        try:
            raster.set_crs(crs)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error setting CRS for raster: {str(e)}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise RasterCalcError(str(e))
