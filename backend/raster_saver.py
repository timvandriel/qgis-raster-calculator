import os
from qgis.core import QgsProject, QgsRasterLayer, QgsMessageLog, Qgis
from .exceptions import RasterCalcError, RasterSaveError
import traceback
import tempfile


class RasterSaver:
    """
    Handles saving and post-processing of raster results.
    Responsible for saving the raster output to disk,
    adding it to the QGIS project.
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
            # DEBUG: Check file before save
            print(f"🔍 DEBUG: File exists before save: {os.path.exists(output_path)}")

            # The actual save call
            print(f"🔍 DEBUG: Calling raster.save() now...")
            raster.save(output_path, driver=driver)
            print(f"🔍 DEBUG: raster.save() completed without exception")

            # DEBUG: Check file after save
            file_exists_after = os.path.exists(output_path)
            file_size = os.path.getsize(output_path) if file_exists_after else 0

            # Only proceed with QGIS layer addition if file actually exists
            if file_exists_after and file_size > 0:
                # Automatically add the saved raster to the QGIS project
                QgsProject.instance().addMapLayer(
                    QgsRasterLayer(
                        output_path, os.path.basename(output_path).split(".")[0]
                    )
                )
                # Log a success message in the QGIS message log
                QgsMessageLog.logMessage(
                    f"Raster saved to {output_path}",
                    "Lazy Raster Calculator",
                    Qgis.Info,
                )
            else:
                QgsMessageLog.logMessage(
                    f"Warning: Save operation completed but file was not created: {output_path}",
                    "Lazy Raster Calculator",
                    Qgis.Warning,
                )

        except Exception as e:
            print(f"❌ DEBUG: Exception occurred: {type(e).__name__}: {str(e)}")
            tb = traceback.format_exc()
            print(f"❌ DEBUG: Full traceback:\n{tb}")
            QgsMessageLog.logMessage(
                f"Error saving raster: {str(e)}\nTraceback:\n{tb}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )

    def temp_output(self, raster, name):
        """
        Generates a temporary output path for the raster and saves it.
        Parameters:
        raster: The raster object to be saved (from raster-tools).
        name (str): The name to use for the temporary file.
        Returns:
        None
        """
        output_path = os.path.join(tempfile.gettempdir(), f"{name}.tif")
        print(f"🔍 DEBUG: Generated temporary output path: {output_path}")
        self.save(raster, output_path)
