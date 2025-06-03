import os
from qgis.core import QgsProject, QgsRasterLayer, QgsMessageLog, Qgis
from .exceptions import RasterCalcError, RasterSaveError
import traceback


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
            # DEBUG: Print what we're trying to save
            print(
                f"🔍 DEBUG: Attempting to save with driver '{driver}' to '{output_path}'"
            )
            print(f"🔍 DEBUG: Raster type: {type(raster)}")
            print(
                f"🔍 DEBUG: Raster shape: {getattr(raster, 'shape', 'No shape attribute')}"
            )
            print(
                f"🔍 DEBUG: Raster dtype: {getattr(raster, 'dtype', 'No dtype attribute')}"
            )

            # DEBUG: Check if output directory exists
            output_dir = os.path.dirname(output_path)
            print(
                f"🔍 DEBUG: Output directory '{output_dir}' exists: {os.path.exists(output_dir)}"
            )

            # DEBUG: Check file before save
            print(f"🔍 DEBUG: File exists before save: {os.path.exists(output_path)}")

            # The actual save call
            print(f"🔍 DEBUG: Calling raster.save() now...")
            raster.save(output_path, driver=driver)
            print(f"🔍 DEBUG: raster.save() completed without exception")

            # DEBUG: Check file after save
            file_exists_after = os.path.exists(output_path)
            file_size = os.path.getsize(output_path) if file_exists_after else 0
            print(f"🔍 DEBUG: File exists after save: {file_exists_after}")
            print(f"🔍 DEBUG: File size after save: {file_size} bytes")

            # Only proceed with QGIS layer addition if file actually exists
            if file_exists_after and file_size > 0:
                # Automatically add the saved raster to the QGIS project
                QgsProject.instance().addMapLayer(
                    QgsRasterLayer(output_path, os.path.basename(output_path))
                )
                # Log a success message in the QGIS message log
                QgsMessageLog.logMessage(
                    f"Raster saved to {output_path}",
                    "Lazy Raster Calculator",
                    Qgis.Info,
                )
                print(f"✅ DEBUG: Successfully saved and added to project")
            else:
                print(f"❌ DEBUG: File was not created or is empty")
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
