from qgis.PyQt.QtGui import *
from qgis.PyQt.QtWidgets import *
from qgis.core import *
from qgis.gui import QgsMapToolEmitPoint
import math
import rasterio
import sys
import numpy as np

sys.setrecursionlimit(10**5)

class HydroFlood:

    def __init__(self, iface):
        # save reference to the QGIS interface
        self.iface = iface

    def initGui(self):
        # create action that will start plugin initialization
        self.action = QAction("Enable Hydro Picker Tool", self.iface.mainWindow())
        self.action.triggered.connect(self.clickTool)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Hydro Picker", self.action)

        self.canvas = self.iface.mapCanvas()

        # this QGIS tool emits as QgsPoint after each click on the map canvas
        self.pointTool = QgsMapToolEmitPoint(self.canvas)
        self.pointTool.canvasClicked.connect(self.clicked)

        self.initialize = QAction("Start Plugin", self.iface.mainWindow())
        self.initialize.triggered.connect(self.start)
        self.iface.addToolBarIcon(self.initialize)
        self.iface.addPluginToMenu("&Hydro Picker", self.initialize)

        self.flood = QAction("Flood Water Bodies", self.iface.mainWindow())
        self.flood.triggered.connect(self.floodHydro)
        self.iface.addToolBarIcon(self.flood)
        self.iface.addPluginToMenu("&Hydro Picker", self.flood)

        self.clear = QAction("Remove All Points", self.iface.mainWindow())
        self.clear.triggered.connect(self.clearPoints)
        self.iface.addPluginToMenu("&Hydro Picker", self.clear)

        self.eraser = QAction("Raster Eraser", self.iface.mainWindow())
        self.eraser.triggered.connect(self.rasterEraser)
        self.iface.addPluginToMenu("&Hydro Picker", self.eraser)
        self.eraserTool = QgsMapToolEmitPoint(self.canvas)
        self.eraserTool.canvasClicked.connect(self.erase)

        self.iface.registerMainWindowAction(self.action, None)
        self.iface.registerMainWindowAction(self.initialize, None)
        self.iface.registerMainWindowAction(self.flood, None)
        self.iface.registerMainWindowAction(self.clear, 'Ctrl+C')
        self.iface.registerMainWindowAction(self.eraser, None)

        self.points = None
        self.rasterLayer = None
        self.hydroLayer = None
        self.prevClick = None

    def unload(self):
        # remove the plugin menu item and icon
        self.iface.removePluginMenu("&Hydro Picker", self.action)
        self.iface.removePluginMenu("&Hydro Picker", self.initialize)
        self.iface.removePluginMenu("&Hydro Picker", self.flood)
        self.iface.removePluginMenu("&Hydro Picker", self.clear)
        self.iface.removePluginMenu("&Hydro Picker", self.eraser)
        self.iface.removeToolBarIcon(self.action)
        self.iface.removeToolBarIcon(self.initialize)
        self.iface.removeToolBarIcon(self.flood)

        self.iface.unregisterMainWindowAction(self.action)
        self.iface.unregisterMainWindowAction(self.initialize)
        self.iface.unregisterMainWindowAction(self.flood)
        self.iface.unregisterMainWindowAction(self.clear)
        self.iface.unregisterMainWindowAction(self.eraser)

    def start(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsRasterLayer):
            QMessageBox.information(None, 'Hydro Picker', 'Select raster layer as active layer')
            return

        self.rasterLayer = layer
        
        layers = QgsProject.instance().mapLayersByName("Hydro Picker Points (donotdelete)")
        if len(layers) != 0 and isinstance(layers[0], QgsVectorLayer):
            self.points = layers[0]
        else:
            crs = self.canvas.mapSettings().destinationCrs().authid()
            uri = "point?crs=" + crs #+ "&field=id:integer"
            self.points = QgsVectorLayer(uri, "Hydro Picker Points (donotdelete)",  "memory")
            QgsProject.instance().addMapLayer(self.points)

        self.pointsDP = self.points.dataProvider()

        self.rasterDP = self.rasterLayer.dataProvider()
        path = self.rasterDP.dataSourceUri().rsplit('.tif')[0] + '_Hydro.tif'

        layers = QgsProject.instance().mapLayersByName('Hydro Raster')
        hydroLayer = None
        if len(layers) != 0:
            for layer in layers:
                if isinstance(layer, QgsRasterLayer) and layer.dataProvider().dataSourceUri() == path:
                    hydroLayer = layers[0]
                    break

        raster = rasterio.open(self.rasterDP.dataSourceUri())

        if hydroLayer is None:
            hydroraster = rasterio.open(path, 'w', driver='GTiff', height=raster.height, width=raster.width,
                                count=1, dtype='int8', crs=raster.crs, transform=raster.transform, nodata=0)
            hydroraster.close()
            hydroLayer = QgsRasterLayer(path, 'Hydro Raster')
            QgsProject.instance().addMapLayer(hydroLayer)

        raster.close()
        self.hydroLayer = hydroLayer

    def clickTool(self):
        if isinstance(self.points, QgsVectorLayer):
            self.canvas.setMapTool(self.pointTool)

    def rasterEraser(self):
        if isinstance(self.rasterLayer, QgsRasterLayer):
            self.canvas.setMapTool(self.eraserTool)

    def clicked(self, point, button):
        if not isinstance(self.points, QgsVectorLayer):
            return

        fet = QgsFeature()
        fet.setGeometry(QgsGeometry.fromPointXY(point))
        self.pointsDP.addFeatures([fet])

        self.points.updateExtents()
        self.points.triggerRepaint()

    def clearPoints(self):
        if not isinstance(self.points, QgsVectorLayer):
            return

        self.points.startEditing()
        self.points.selectAll()
        self.points.deleteSelectedFeatures()
        self.points.commitChanges()

    def erase(self, point, button):
        if not isinstance(self.hydroLayer, QgsRasterLayer):
            return

        pt = QgsPoint(point.x(), point.y())
        rasterCoords = self.rasterDP.transformCoordinates(pt, 1)
        index = (math.floor(rasterCoords.x()), math.floor(rasterCoords.y()))

        if self.prevClick is None:
            self.prevClick = index
            return

        block = QgsRasterBlock(Qgis.Int8, abs(index[0] - self.prevClick[0]), abs(index[1] - self.prevClick[1]))
        block.setIsNoData()
        hdp = self.hydroLayer.dataProvider()
        hdp.setEditable(True)
        x = self.prevClick[0]
        if x > index[0]:
            x = index[0]
        y = self.prevClick[1]
        if y > index[1]:
            y = index[1]
        res = hdp.writeBlock(block, 1, x, y)
        hdp.setEditable(False)
        self.hydroLayer.triggerRepaint()
        self.prevClick = None
        

    def floodHydro(self):
        if not isinstance(self.points, QgsVectorLayer) and not isinstance(self.rasterLayer, QgsRasterLayer):
            QMessageBox.information(None, 'Hydro Picker', 'Start First')
            return
            
        raster = rasterio.open(self.rasterDP.dataSourceUri())
        self.data = raster.read(1)
        self.hydrodata = np.zeros(self.data.shape, np.int8)
        
        for feature in self.points.getFeatures():
            point = feature.geometry().asPoint()
            pt = QgsPoint(point.x(), point.y())

            rasterCoords = self.rasterDP.transformCoordinates(pt, 1)
            index = (math.floor(rasterCoords.x()), math.floor(rasterCoords.y()))
            # QMessageBox.information(None, 'Hydro Picker', str(index))

            self.value = self.data[index[1], index[0]]; self.bounds = (raster.height - 1, raster.width - 1)
            self.dfs(index, 0)
            


        raster.close()
        path = self.hydroLayer.dataProvider().dataSourceUri()
        hydroraster = rasterio.open(path, 'r+', driver='GTiff', height=raster.height, width=raster.width,
                            count=1, dtype='int8', crs=raster.crs, transform=raster.transform, nodata=0)
        prev = hydroraster.read(1)
        np.add(self.hydrodata, prev, self.hydrodata)

        hydroraster.write_band(1, self.hydrodata)
        hydroraster.close()
        
        # self.hydroLayer.dataProvider().reload() # dont know if this does anything
        self.hydroLayer.triggerRepaint()
        self.data = None
        self.hydrodata = None

    def dfs(self, index, rec):
        if index[1] > self.bounds[0] or index[0] > self.bounds[1] or index[1] < 0 or index[0] < 0:
            return
        if self.hydrodata[index[1], index[0]] != 0:
            return
        if self.data[index[1], index[0]] != self.value:
            return

        self.hydrodata[index[1], index[0]] = 1
        self.dfs((index[0] + 1, index[1]), rec + 1)
        self.dfs((index[0], index[1] - 1), rec + 1)
        self.dfs((index[0] - 1, index[1]), rec + 1)
        self.dfs((index[0], index[1] + 1), rec + 1)
