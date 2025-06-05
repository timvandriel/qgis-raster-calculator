class LazyLayer:
    """
    Represents a lazy raster layer, with metadata
    """

    def __init__(self, name: str, raster):
        self.name = name
        self.raster = raster  # raster_tools.Raster object
        self.computed = False  # Flag to indicate if the raster has been computed

    def __repr__(self):
        return f"<LazyLayer name='{self.name}' computed={self.computed}>"

    @property
    def display_name(self):
        """
        Appends "(Lazy)" to the layer name for display purposes.
        """
        return f"{self.name} (Lazy)" if not self.computed else self.name


class LazyLayerRegistry:
    """
    Manages user-named lazy layers for later use and computation.
    """

    def __init__(self):
        self._layers = {}  # Dictionary to store LazyLayer objects by name

    def register(self, name: str, raster) -> LazyLayer:
        """
        Registers a new lazy layer with the given name and raster object.

        Args:
            name (str): The name of the lazy layer.
            raster: The raster object (from raster-tools).

        Returns:
            LazyLayer: The created LazyLayer object.
        """
        if name in self._layers:
            raise ValueError(f"Lazy layer '{name}' already exists.")

        lazy_layer = LazyLayer(name, raster)
        self._layers[name] = lazy_layer
        return lazy_layer

    def get(self, name: str) -> LazyLayer:
        """
        Retrieves a lazy layer by name.

        Args:
            name (str): The name of the lazy layer to retrieve.

        Returns:
            LazyLayer: The LazyLayer object if found.
        """
        return self._layers[name]

    def has(self, name: str) -> bool:
        """
        Checks if a lazy layer with the given name is registered.

        Args:
            name (str): The name of the lazy layer to check.

        Returns:
            bool: True if the lazy layer exists, False otherwise.
        """
        return name in self._layers

    def all_layers(self) -> list[LazyLayer]:
        """
        Returns a list of all registered lazy layers.

        Returns:
            list[LazyLayer]: List of all LazyLayer objects.
        """
        return list(self._layers.values())

    def exists(self, name: str) -> bool:
        """
        Checks if a lazy layer with the given name exists.

        Args:
            name (str): The name of the lazy layer to check.

        Returns:
            bool: True if the lazy layer exists, False otherwise.
        """
        return name in self._layers

    def mark_computed(self, name: str) -> None:
        """
        Marks a lazy layer as computed.

        Args:
            name (str): The name of the lazy layer to mark as computed.

        Raises:
            KeyError: If the lazy layer does not exist.
        """
        if name not in self._layers:
            raise KeyError(f"Lazy layer '{name}' not found.")

        self._layers[name].computed = True

    def clear(self) -> None:
        """
        Clears all registered lazy layers.
        This will remove all lazy layers from the registry.
        """
        self._layers.clear()
