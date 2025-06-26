import raster_tools
import xarray as xr
import numpy as np
from .layer_manager import LayerManager
from .exceptions import (
    RasterToolsUnavailableError,
    LayerNotFoundError,
    BandMismatchError,
    RasterExtentError,
)
from .lazy_manager import get_lazy_layer_registry
import re
from shapely import overlaps


class RasterManager:
    """
    Manages conversion of QGIS raster layers into `raster_tools.Raster` objects.
    Uses a cache to avoid redundant conversions and improves performance.
    """

    def __init__(self, layer_manager: LayerManager):
        """
        Initializes the RasterManager with a reference to the LayerManager.

        Args:
            layer_manager (LayerManager): The manager used to retrieve QGIS raster layers.
        """
        self.layer_manager = layer_manager
        self.lazy_registry = get_lazy_layer_registry()
        self.dtype = {
            "Byte": "uint8",
            "Int16": "int16",
            "UInt16": "uint16",
            "UInt32": "uint32",
            "Int32": "int32",
            "Float32": "float32",
            "Float64": "float64",
            "CInt16": "complex64",
            "CInt32": "complex128",
            "CFloat32": "complex64",
            "CFloat64": "complex128",
            "Int8": "int8",
        }

    def get_raster(self, name: str):
        """
        Retrieves a raster_tools.Raster object for the given name.
        If a band is specified using '@n', returns a single-band Raster.

        Args:
            name (str): Raster layer name, optionally with "@<band>" suffix.

        Returns:
            raster_tools.Raster
        """
        # Extract base name and band (if present)
        match = re.match(r"^(.+?)@(\d+)$", name)
        if match:
            base_name = match.group(1)
            band_index = int(match.group(2))
        else:
            base_name = name
            band_index = None

        # Strip " (Lazy)" from name if present
        if base_name.endswith(" (Lazy)"):
            base_name = base_name[:-7]

        # Lazy lookup first
        if self.lazy_registry.has(base_name):
            raster = self.lazy_registry.get(base_name)
        else:
            # Load from QGIS project
            qgis_layer = self.layer_manager.get_raster_layer(base_name)
            if not qgis_layer:
                raise LayerNotFoundError(f"Layer '{base_name}' not found in project.")
            try:
                raster = raster_tools.Raster(qgis_layer.source())
            except Exception as e:
                raise RasterToolsUnavailableError(
                    f"Could not load Raster from layer '{base_name}': {str(e)}"
                )

        # If a specific band is requested
        if band_index is not None:
            try:
                return raster.get_bands([band_index])
            except IndexError:
                raise RasterToolsUnavailableError(
                    f"Band {band_index + 1} not found in raster '{base_name}'."
                )
        return raster

    def get_rasters(self, names: list[str]) -> dict[str, raster_tools.Raster]:
        """
        Retrieves a dictionary of `raster_tools.Raster` objects for a list of layer names.

        Args:
            names (list[str]): List of raster layer names to retrieve.

        Returns:
            dict[str, raster_tools.Raster]: Dictionary mapping names to `Raster` objects.
        """
        rasters = {}
        for name in names:
            raster = self.get_raster(name)
            if raster:
                rasters[name] = raster
            else:
                raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")
        return rasters

    def add_lazy_layer(self, name: str, raster: raster_tools.Raster):
        """
        Adds a raster as a lazy layer to the lazy registry.
        Args:
            name (str): The name of the lazy layer.
            raster (raster_tools.Raster): The raster object to register.
        Returns:
            raster_tools.Raster: The lazy layer registered in the lazy registry.
        """
        lazy_layer = self.lazy_registry.register(name, raster)
        return lazy_layer

    def reproject_if_needed(self, raster, target_crs):
        """Check if the raster's CRS matches the target CRS and reproject if necessary.
        Args:
            raster (raster_tools.Raster): The raster object to check.
            target_crs (str): The target CRS in AUTHID format (e.g., "EPSG:4326").
        Returns:
            raster_tools.Raster: The raster object, reprojected to the specified crs if necessary.
        """
        if raster.crs.to_string() == target_crs:
            return raster
        return raster.reproject(crs_or_geobox=target_crs)

    def _approx_geobox_area(self, geobox):
        """
        Estimates the area of a geobox by mulitplying its rows, columns, and pixel size.
        Args:
            geobox (raster_tools.Geobox): The geobox to estimate the area for.
        Returns:
            float: The estimated area of the geobox.
        """
        rows, cols = geobox.shape[0], geobox.shape[1]  # Get number of rows and columns
        px_w, px_h = geobox.affine.a, abs(geobox.affine.e)  # Get pixel width and height
        return rows * cols * px_w * px_h

    def _align_to_smallest_extent(self, rasters: dict):
        """Aligns multiple rasters to the smallest extent by reprojecting them to a common geobox.
        Args:
            rasters (dict): A dictionary of raster names and their corresponding raster objects.
        Returns:
            tuple: A tuple containing the reference raster name and a dictionary of aligned rasters.
        """
        # If only one raster, return it as the reference
        if len(rasters) <= 1:
            return next(iter(rasters)), rasters

        # Find the raster with the smallest geobox area to use as reference
        ref_name, ref_raster = min(
            rasters.items(),
            key=lambda item: self._approx_geobox_area(item[1].geobox),
        )
        # Use the reference raster's geobox for alignment
        ref_grid = ref_raster.geobox
        ref_coords_x = ref_raster.xdata.coords[
            "x"
        ].values  # Get reference x-coordinates
        ref_coords_y = ref_raster.xdata.coords[
            "y"
        ].values  # Get reference y-coordinates
        aligned_rasters = {}

        # Align all rasters to the reference geobox
        for name, raster in rasters.items():
            if ref_grid == raster.geobox:
                aligned_rasters[name] = raster
            else:
                # Reproject
                reprojected = raster.reproject(crs_or_geobox=ref_grid)
                new_coords_x = reprojected.xdata.coords["x"].values
                new_coords_y = reprojected.xdata.coords["y"].values

                if not (
                    np.array_equal(ref_coords_x, new_coords_x)
                    and np.array_equal(ref_coords_y, new_coords_y)
                ):  # Check if coordinates match
                    # self._compare_coords(
                    #     ref_coords_y,
                    #     new_coords_y,
                    #     axis="y",
                    #     name=name,
                    #     ref_name=ref_name,
                    # )
                    # self._compare_coords(
                    #     ref_coords_x,
                    #     new_coords_x,
                    #     axis="x",
                    #     name=name,
                    #     ref_name=ref_name,
                    # )
                    # Wrap dask array in xarray DataArray with coords/dims from reference
                    xr_da = xr.DataArray(
                        reprojected.data,
                        coords={
                            "x": ref_raster.xdata.coords["x"],
                            "y": ref_raster.xdata.coords["y"],
                            # Add other coords if necessary
                        },
                        dims=ref_raster.xdata.dims,
                    )

                    aligned_rasters[name] = raster_tools.Raster(
                        xr_da
                    )  # Wrap in Raster object
                else:
                    # Coordinates match exactly — just add reprojected raster as is
                    aligned_rasters[name] = reprojected

        return ref_name, aligned_rasters

    def _compare_coords(
        self, ref_coords, other_coords, axis="y", name="unnamed", ref_name="reference"
    ):
        """
        Helper method that ompares coordinates of two rasters along a specified axis and prints differences.
        Args:
            ref_coords (np.ndarray): Reference coordinates to compare against.
            other_coords (np.ndarray): Coordinates from the other raster to compare.
            axis (str): Axis along which to compare ('x' or 'y').
            name (str): Name of the raster being compared.
            ref_name (str): Name of the reference raster.
        """
        diffs = np.abs(ref_coords - other_coords)
        max_diff = np.max(diffs)
        mean_diff = np.mean(diffs)
        num_different = np.count_nonzero(diffs > 0)

        print(
            f"\n[Coord Check] Axis '{axis}' for raster '{name}' compared to '{ref_name}':"
        )
        print(f"  Total values: {len(ref_coords)}")
        print(f"  Values differing: {num_different}")
        print(f"  Max difference: {max_diff:.15f}")
        print(f"  Mean difference: {mean_diff:.15f}")

        if num_different:
            decimals = -np.floor(np.log10(max_diff)).astype(int)
            print(f"  => Coordinates differ at ~{decimals} decimal places")

    def get_dtype(self, dtype_name: str) -> str:
        """
        Returns the numpy dtype corresponding to a QGIS raster data type name.

        Args:
            dtype_name (str): The QGIS raster data type name (e.g., "Byte", "Int16").

        Returns:
            str: The corresponding numpy dtype name.
        """
        return self.dtype.get(dtype_name, "<AUTO>")

    def check_bands(self, rasters: dict):
        """
        Ensures all rasters have the same number of bands.

        Raises:
            BandMismatchError: If the rasters have inconsistent band counts.
        """
        band_counts = {name: raster.nbands for name, raster in rasters.items()}
        unique_counts = set(band_counts.values())

        if len(unique_counts) > 1:
            message = "All rasters must have the same number of bands.\n\n"
            message += "\n".join(
                f"{name}: {count} bands" for name, count in band_counts.items()
            )
            raise BandMismatchError(message)
        return True

    def raster_overlap(self, raster_dict):
        """Checks if all rasters in the dictionary overlap in extent.
        Args:
            raster_dict (dict): Dictionary of raster names and their corresponding raster objects.
        Returns:
            bool: True if all rasters overlap
        Raises:
            RasterExtentError: If any pair of rasters do not overlap in extent.
        """
        if len(raster_dict) <= 1:
            return True
        # Get the polygons representing the extents of all rasters
        raster_polygons = [raster.geobox.extent.geom for raster in raster_dict.values()]
        # Check if all polygons overlap
        for i in range(len(raster_polygons)):
            for j in range(i + 1, len(raster_polygons)):
                if not overlaps(raster_polygons[i], raster_polygons[j]):
                    raise RasterExtentError(
                        f"Rasters '{list(raster_dict.keys())[i]}' and '{list(raster_dict.keys())[j]}' are not in the same extent."
                    )
        return True
