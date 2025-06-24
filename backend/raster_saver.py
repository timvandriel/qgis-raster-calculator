import os
from qgis.core import QgsProject, QgsRasterLayer, QgsMessageLog, Qgis
from .exceptions import RasterCalcError, RasterSaveError
import traceback
import tempfile
import gc
from osgeo import gdal


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
        Returns:
            QgsRasterLayer: The added raster layer in the QGIS project, or None if save failed.
        """
        try:
            # DEBUG: Check file before save
            print(f"🔍 DEBUG: File exists before save: {os.path.exists(output_path)}")

            # The actual save call
            print(f"🔍 DEBUG: Calling raster.save() now...")
            raster.save(output_path, driver=driver, tiled=True)
            print(f"🔍 DEBUG: raster.save() completed without exception")

            # DEBUG: Check file after save
            file_exists_after = os.path.exists(output_path)
            file_size = os.path.getsize(output_path) if file_exists_after else 0

            # Force file to be completely written and closed
            gc.collect()  # Force garbage collection to free up memory
            try:
                ds = gdal.Open(output_path)
                if ds:
                    band = ds.GetRasterBand(1)
                    # Force GDAL to read and calculate stats
                    stats = band.ComputeStatistics(False)
                    print(
                        f"🔍 DEBUG: GDAL computed stats - min: {stats[0]}, max: {stats[1]}"
                    )
                    ds = None  # Close the dataset
            except Exception as e:
                print(f"Could not verify file with GDAL: {e}")
            # Only proceed with QGIS layer addition if file actually exists
            if file_exists_after and file_size > 0:
                layer = QgsRasterLayer(
                    output_path, os.path.basename(output_path).split(".")[0]
                )
                QgsProject.instance().addMapLayer(layer)
                QgsMessageLog.logMessage(
                    f"Raster saved to {output_path}",
                    "Lazy Raster Calculator",
                    Qgis.Info,
                )
                return layer  # Return the layer
                # Log a success message in the QGIS message log
            else:
                QgsMessageLog.logMessage(
                    f"Warning: Save operation completed but file was not created: {output_path}",
                    "Lazy Raster Calculator",
                    Qgis.Warning,
                )
                return None  # Return None if file was not created

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
            tuple: A tuple containing the QgsRasterLayer and the output path.
        """
        output_path = os.path.join(tempfile.gettempdir(), f"{name}.tiff")
        print(f"🔍 DEBUG: Generated temporary output path: {output_path}")
        layer = self.save(raster, output_path)
        return layer, output_path
