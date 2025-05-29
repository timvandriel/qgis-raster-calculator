import os
from qgis.core import QgsProject, QgsRasterLayer, QgsMessageLog, Qgis
from .exceptions import RasterCalcError, RasterSaveError


class RasterSaver:
    """
    Handles saving and post-processing of raster results.
    Responsible for saving the raster output to disk,
    adding it to the QGIS project, and setting the CRS if needed.
    """

    def save(self, raster, output_path: str, driver="GTiff"):
        """
        Save the raster to the specified output path using the given driver
        and automatically add it to the current QGIS project.

        Parameters:
            raster: The raster object to be saved (from raster-tools).
            output_path (str): The file path where the raster should be saved.
            driver (str): The raster file format driver (default is "GTiff").

        Raises:
            RasterSaveError: If the raster cannot be saved.
        """
        try:
            raster.save(output_path, driver=driver)

            # Automatically add the saved raster to the QGIS project
            QgsProject.instance().addMapLayer(
                QgsRasterLayer(output_path, os.path.basename(output_path))
            )

            # Log a success message in the QGIS message log
            QgsMessageLog.logMessage(
                f"Raster saved to {output_path}", "Lazy Raster Calculator", Qgis.Info
            )
        except Exception as e:
            # Log the error and raise a custom exception
            QgsMessageLog.logMessage(
                f"Error saving raster: {str(e)}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise RasterSaveError(str(e))

    def reproject_to_CRS(self, raster, target_crs, projection=None):
        """
        Reprojects the raster to the specified CRS.

        Parameters:
            raster: The raster object to be reprojected.
            target_crs: The target coordinate reference system (CRS) to reproject to.
            reprojection: Optional projection parameters (default is None). May include later.

        Returns:
            The reprojected raster object.

        Raises:
            RasterCalcError: If the reprojection fails.
        """
        try:
            return raster.reproject(target_crs, projection=projection)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error reprojecting raster: {str(e)}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise RasterCalcError(f"Reprojection failed: {str(e)}")
