# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LazyRasterCalculatorDockWidget
                                 A QGIS plugin
 A lazy evalutation raster calculator using raster-tools.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2025-05-01
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Tim Van Driel
        email                : timothy.vandriel@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os

from qgis.PyQt import QtGui, QtWidgets, uic
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsProject,
    QgsMapLayerType,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsMapLayer,
)
from qgis.gui import QgsMessageBar, QgsProjectionSelectionDialog
from qgis.utils import iface
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QInputDialog
from .backend import *
import traceback


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "lazy_raster_calculator_dockwidget_base.ui")
)


class LazyRasterCalculatorDockWidget(QtWidgets.QDockWidget, FORM_CLASS):

    closingPlugin = pyqtSignal()

    def __init__(self, parent=None):
        """Constructor."""
        super(LazyRasterCalculatorDockWidget, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://doc.qt.io/qt-5/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        # Hooking into the context menu of the layer tree
        self.layer_tree_view = iface.layerTreeView()
        self.layer_tree_view.contextMenuAboutToShow.connect(self.on_context_menu)

        # check if layers were added or removed
        QgsProject.instance().layersAdded.connect(self.populate_raster_layer_list)
        QgsProject.instance().layerRemoved.connect(self.populate_raster_layer_list)

        # Connect double-click event to populate expression box
        self.rasterLayerListWidget.itemDoubleClicked.connect(
            self.handle_layer_double_click
        )

        # buttons for raster calculator
        self.plusButton.clicked.connect(lambda: self.insert_operator("+"))
        self.minusButton.clicked.connect(lambda: self.insert_operator("-"))
        self.multiplyButton.clicked.connect(lambda: self.insert_operator("*"))
        self.divideButton.clicked.connect(lambda: self.insert_operator("/"))
        self.openParenButton.clicked.connect(lambda: self.insert_operator("("))
        self.closeParenButton.clicked.connect(lambda: self.insert_operator(")"))
        self.clearButton.clicked.connect(self.clear_expression)

        # button for ouput path
        self.outputPathButton.clicked.connect(self.select_output_path)

        # crs button and combobox
        self.crsSelectButton.clicked.connect(self.open_crs_dialog)
        self.populate_crs_combobox()

        # okay and cancel buttons
        self.okButton.clicked.connect(self.on_ok_clicked)
        self.cancelButton.clicked.connect(self.on_cancel_clicked)

        # check for valid expression
        self.expressionBox.textChanged.connect(self.on_expression_changed)

        # check for output path changes
        self.outputPathLineEdit.textChanged.connect(self.on_output_path_changed)

        # Initialize managers
        self.layer_manager = LayerManager()
        self.raster_manager = RasterManager(self.layer_manager)
        self.expression_evaluator = ExpressionEvaluator(self.raster_manager)
        self.lazy_registry = get_lazy_layer_registry()
        self.raster_saver = RasterSaver()

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_raster_layer_list()

    def on_context_menu(self, menu):
        """Adds custom action to the context menu for lazy raster layers"""
        layer = self.layer_tree_view.currentLayer()
        if not layer:
            return

        if layer.type() == QgsMapLayer.RasterLayer and layer.customProperty(
            "is_lazy", False
        ):
            menu.addSeparator()
            compute = QAction("Compute Lazy Layer", menu)
            compute.triggered.connect(lambda: self.compute_lazy_layer(layer))
            menu.addAction(compute)

    def compute_lazy_layer(self, layer):
        layer_name = layer.customProperty("lazy_name", None)
        if not layer_name:
            QMessageBox.warning(
                self,
                "Error",
                "This layer does not have a valid lazy name. Cannot compute.",
            )
            return
        raster = self.lazy_registry.get(layer_name)
        raster = raster.raster
        self.raster_saver.temp_output(raster, layer_name)
        QgsProject.instance().removeMapLayer(layer.id())

    def populate_raster_layer_list(self):
        """Populate the list widget with names of all visible raster layers, including lazy ones."""
        self.rasterLayerListWidget.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayerType.RasterLayer:
                name = layer.name()

                # Check if it's a lazy placeholder
                if layer.customProperty("is_lazy", False):
                    # Optionally, retrieve the original lazy name (in case display name differs)
                    lazy_name = layer.customProperty("lazy_name", name)
                    display_name = f"{lazy_name} (Lazy)"
                else:
                    display_name = name

                self.rasterLayerListWidget.addItem(display_name)

    def handle_layer_double_click(self, item):
        """Handle double-click event on a layer name in the list widget.
        This method is called when the user double-clicks on a layer name in the list.
        It inserts the layer name into the expression box at the current cursor position.
        """
        layer_name = '"' + item.text() + '"'
        self.insert_text_into_text_edit(layer_name)

    def insert_operator(self, operator):
        """Insert an operator at the current cursor position in the expression box.
        This method is called when the user clicks on an operator button (e.g., +, -, *, /).
        """
        self.insert_text_into_text_edit(operator)

    def clear_expression(self):
        """Clear the expression box."""
        self.expressionBox.clear()

    def insert_text_into_text_edit(self, text):
        """Insert text at the current cursor position in the expression box."""
        cursor = self.expressionBox.textCursor()
        cursor.insertText(text)
        self.expressionBox.setTextCursor(cursor)
        self.expressionBox.setFocus()

    def update_expression_status(self, is_valid):
        """Update the status label based on the validity of the expression."""
        if is_valid:
            self.expressionStatusLabel.setText("Valid expression")
            self.expressionStatusLabel.setStyleSheet("color: green;")
        else:
            self.expressionStatusLabel.setText("Invalid expression")
            self.expressionStatusLabel.setStyleSheet("color: red;")

    def on_expression_changed(self):
        """Handle changes in the expression box."""
        text = self.expressionBox.toPlainText().strip()
        valid = ExpressionEvaluator.is_valid_expression(text)
        self.update_expression_status(valid)

    def open_crs_dialog(self):
        """Open the CRS selection dialog and set the selected CRS."""
        initial_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        dlg = QgsProjectionSelectionDialog(self)
        dlg.setCrs(initial_crs)

        if dlg.exec_() == 1:  # User pressed OK
            selected_crs = dlg.crs()
            selected_authid = selected_crs.authid()
            selected_label = f"{selected_authid} - {selected_crs.description()}"

            # Check if it's already in the combo box
            found = False
            for i in range(self.crsComboBox.count()):
                if self.crsComboBox.itemData(i) == selected_authid:
                    self.crsComboBox.setCurrentIndex(i)
                    found = True
                    break

            # If not found, add it
            if not found:
                self.crsComboBox.addItem(selected_label, selected_authid)
                self.crsComboBox.setCurrentIndex(self.crsComboBox.count() - 1)

    def populate_crs_combobox(self):
        """Populate the CRS combo box with available coordinate reference systems."""
        self.crsComboBox.clear()

        # Default CRS 4326
        default_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self.crsComboBox.addItem(
            f"{default_crs.authid()} - {default_crs.description()}",
            default_crs.authid(),
        )

        # Project CRS
        project_crs = QgsProject.instance().crs()
        self.crsComboBox.addItem(
            f"Project CRS - {project_crs.authid()} - {project_crs.description()}",
            project_crs.authid(),
        )

    def _add_file_extension(self, file_name, selected_filter):
        """Add appropriate file extension based on the selected filter if missing."""
        if selected_filter.startswith("GeoTIFF") and not file_name.endswith(".tif"):
            file_name += ".tif"
        elif selected_filter.startswith("Erdas Imagine") and not file_name.endswith(
            ".img"
        ):
            file_name += ".img"
        elif selected_filter.startswith("ASCII Grid") and not file_name.endswith(
            ".asc"
        ):
            file_name += ".asc"
        elif selected_filter.startswith("PNG") and not file_name.endswith(".png"):
            file_name += ".png"
        elif selected_filter.startswith("ENVI") and not file_name.endswith(".dat"):
            file_name += ".dat"
        return file_name

    def select_output_path(self):
        """Open a file dialog to select the output path for the raster."""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Select Output Path",
            "",
            (
                "GeoTIFF (*.tif);;"
                "Erdas Imagine (*.img);;"
                "ASCII Grid (*.asc);;"
                "PNG (*.png);;"
                "ENVI (*.dat);;"
                "All Files (*)"
            ),
            options=options,
        )
        if file_name:
            self.selectedFilter = selected_filter

            file_name = self._add_file_extension(file_name, selected_filter)
            self.outputPathLineEdit.setText(file_name)

    def _select_driver(self):
        f = self.selectedFilter
        if f.startswith("GeoTIFF"):
            return "GTiff"
        elif f.startswith("Erdas Imagine"):
            return "HFA"
        elif f.startswith("ASCII Grid"):
            return "AAIGrid"
        elif f.startswith("PNG"):
            return "PNG"
        elif f.startswith("ENVI"):
            return "ENVI"
        else:
            raise ValueError(
                "Unsupported file format selected: {}".format(self.selectedFilter)
            )

    def on_output_path_changed(self, text):
        """Infer the driver based on the typed file extension."""
        ext = os.path.splitext(text)[1].lower()

        ext_to_filter = {
            ".tif": "GeoTIFF (*.tif)",
            ".tiff": "GeoTIFF (*.tif)",
            ".img": "Erdas Imagine (*.img)",
            ".asc": "ASCII Grid (*.asc)",
            ".png": "PNG (*.png)",
            ".dat": "ENVI (*.dat)",
        }

        if ext in ext_to_filter:
            self.selectedFilter = ext_to_filter[ext]
        elif ext == "":
            # No extension → default to GeoTIFF
            self.selectedFilter = "GeoTIFF (*.tif)"
        else:
            # Unknown extension → clear selectedFilter to trigger warning later
            self.selectedFilter = None

    def on_ok_clicked(self):
        expression = self.expressionBox.toPlainText().strip()
        output_path = self.outputPathLineEdit.text().strip()
        is_lazy = self.lazyRadioButton.isChecked()
        crs_index = self.crsComboBox.currentIndex()
        target_crs_authid = self.crsComboBox.itemData(crs_index)

        if not expression or (not output_path and not is_lazy):
            QMessageBox.warning(
                self,
                "Missing Information",
                "Please enter both an expression and output path (unless creating a lazy layer).",
            )
            return

        try:

            # Prompt for name if lazy
            result_name = None
            if is_lazy:
                result_name, ok = QInputDialog.getText(
                    self, "Lazy Layer Name", "Enter a name for the lazy layer:"
                )
                if not ok or not result_name.strip():
                    QMessageBox.warning(
                        self, "Invalid Name", "Lazy layer name cannot be empty."
                    )
                    return
                result_name = result_name.strip()

            # Evaluate (this registers the lazy layer if is_lazy)
            result = self.expression_evaluator.evaluate(
                expression,
                target_crs_authid,
                result_name=result_name if is_lazy else None,
            )

            if is_lazy:
                # Add placeholder fake QgsRasterLayer
                uri = f"NotComputed:{result_name}"
                fake_layer = QgsRasterLayer(uri, f"{result_name} (Lazy)")
                fake_layer.setCustomProperty("is_lazy", True)
                fake_layer.setCustomProperty("lazy_name", result_name)
                QgsProject.instance().addMapLayer(fake_layer)

                self.populate_raster_layer_list()

                QMessageBox.information(
                    self,
                    "Lazy Evaluation",
                    f"Lazy layer '{result_name}' has been created and added as a placeholder.",
                )
                return

            driver = self._select_driver()
            if driver == "PNG":
                result = result.astype("uint16")  # PNG requires uint8 or uint16
            elif driver == "AAIGrid":
                result = result.astype("float64")  # AAIGrid requires float64
            try:
                # Add this right before raster_saver.save(result, output_path, driver=driver)
                print(
                    f"🔍 MAIN DEBUG: About to save with driver='{driver}' from filter='{self.selectedFilter}'"
                )
                print(f"🔍 MAIN DEBUG: Output path='{output_path}'")

                # Quick test to see what methods the raster object has
                print(
                    f"🔍 MAIN DEBUG: Raster object methods: {[m for m in dir(result) if 'save' in m.lower()]}"
                )
                # Ensure the correct extension is added if missing
                output_path = self._add_file_extension(output_path, self.selectedFilter)
                self.outputPathLineEdit.setText(
                    output_path
                )  # Update UI to show corrected path
                self.raster_saver.save(result, output_path, driver=driver)
            except Exception as e:
                print(f"Error saving file: {str(e)}")
                return
            if os.path.exists(output_path):
                print("✅ File was saved.")
            else:
                print("❌ Save operation failed silently.")

            QMessageBox.information(
                self,
                "Success",
                f"Raster saved to:\n{output_path}",
            )

        except InvalidExpressionError as e:
            QMessageBox.critical(self, "Invalid Expression", str(e))
        except LayerNotFoundError as e:
            QMessageBox.critical(self, "Missing Layers", str(e))
        except RasterToolsUnavailableError as e:
            QMessageBox.critical(self, "Raster Tools Error", str(e))
        except RasterSaveError as e:
            QMessageBox.critical(self, "Save Error", str(e))
        except Exception as e:
            tb = traceback.format_exc()
            QMessageBox.critical(
                self,
                "Unexpected Error",
                f"An unexpected error occurred:\n{str(e)}\n\nTraceback:\n{tb}",
            )

    def on_cancel_clicked(self):
        """Handle cancel button click event"""
        self.clear_expression()
        self.outputPathLineEdit.clear()
        self.crsComboBox.setCurrentIndex(0)
        self.lazyRadioButton.setChecked(True)
        self.populate_raster_layer_list()
        self.populate_crs_combobox()
        self.update_expression_status(False)
