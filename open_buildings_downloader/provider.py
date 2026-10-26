import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithm import DownloadBuildings


class Provider(QgsProcessingProvider):
    def id(self):
        return 'openbuildings'

    def name(self):
        return 'Google Open Buildings'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.svg'))

    def loadAlgorithms(self):
        self.addAlgorithm(DownloadBuildings())
