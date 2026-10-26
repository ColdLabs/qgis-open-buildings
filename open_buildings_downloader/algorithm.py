import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
)
from qgis.PyQt.QtCore import QCoreApplication, QMetaType
from qgis.PyQt.QtGui import QIcon

from . import s2, tiles
from .style import CONFIDENCE_STYLE

ICON = os.path.join(os.path.dirname(__file__), 'icon.svg')
WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')
POLYGONS, POINTS, BOTH = 0, 1, 2


def cache_dir():
    return os.path.join(
        QgsApplication.qgisSettingsDirPath(), 'cache', 'open_buildings'
    )


def tr(text):
    return QCoreApplication.translate('OpenBuildings', text)


class DownloadBuildings(QgsProcessingAlgorithm):
    EXTENT = 'EXTENT'
    AREA = 'AREA'
    GEOMETRY = 'GEOMETRY'
    MIN_CONFIDENCE = 'MIN_CONFIDENCE'
    MAX_DOWNLOAD_MB = 'MAX_DOWNLOAD_MB'
    OUTPUT_POLYGONS = 'OUTPUT_POLYGONS'
    OUTPUT_POINTS = 'OUTPUT_POINTS'

    def name(self):
        return 'download'

    def displayName(self):
        return tr('Download buildings')

    def createInstance(self):
        return DownloadBuildings()

    def icon(self):
        return QIcon(ICON)

    def shortHelpString(self):
        return tr(
            'Downloads building footprints from Google Open Buildings v3 '
            '(Africa, South and Southeast Asia, Latin America and the '
            'Caribbean).\n\n'
            'Area: the extent, or the polygons of a layer. When polygons are '
            'set they are used and the extent is ignored. A building is kept '
            'when its centroid falls inside the area.\n\n'
            'Google publishes whole tiles (S2 cells of roughly 100 km), so '
            'the first run in a region downloads the full tiles it touches. '
            'Tiles are cached in the QGIS profile folder and reused '
            'afterwards.\n\n'
            'Confidence: Google keeps buildings at 0.65 and above. Raise it '
            'to drop doubtful detections. Loaded layers are coloured by '
            'confidence: green from 0.75, orange from 0.70, red from 0.65, '
            'grey below.\n\n'
            'Data: Google Open Buildings, CC BY 4.0 or ODbL v1.0. Credit '
            'Google Open Buildings when you publish results.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT, tr('Extent'), optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AREA,
                tr('Area polygons (overrides the extent)'),
                [QgsProcessing.SourceType.TypeVectorPolygon],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.GEOMETRY,
                tr('Download as'),
                [tr('Polygons'), tr('Points'), tr('Polygons and points')],
                defaultValue=POLYGONS,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_CONFIDENCE,
                tr('Minimum confidence'),
                QgsProcessingParameterNumber.Type.Double,
                0.65,
                minValue=0.65,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_DOWNLOAD_MB,
                tr('Stop if new downloads exceed (MB)'),
                QgsProcessingParameterNumber.Type.Integer,
                2000,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_POLYGONS,
                tr('Building polygons'),
                QgsProcessing.SourceType.TypeVectorPolygon,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_POINTS,
                tr('Building points'),
                QgsProcessing.SourceType.TypeVectorPoint,
                optional=True,
            )
        )

    def checkParameterValues(self, parameters, context):
        if not parameters.get(self.AREA) and not parameters.get(self.EXTENT):
            return False, tr('Set an extent or a polygon layer.')
        return super().checkParameterValues(parameters, context)

    def _area(self, parameters, context):
        """The area in EPSG:4326, and whether it is a plain rectangle."""
        source = self.parameterAsSource(parameters, self.AREA, context)
        if source is None:
            geom = self.parameterAsExtentGeometry(
                parameters, self.EXTENT, context, WGS84
            )
            return geom, True
        transform = QgsCoordinateTransform(
            source.sourceCrs(), WGS84, context.transformContext()
        )
        parts = []
        for f in source.getFeatures():
            g = f.geometry()
            if g.isEmpty():
                continue
            g.transform(transform)
            parts.append(g)
        if not parts:
            raise QgsProcessingException(tr('The area layer has no polygons.'))
        return QgsGeometry.unaryUnion(parts), False

    def _cells(self, area):
        bbox = area.boundingBox()
        found = []
        for cell in s2.cells_in_bbox(
            bbox.xMinimum(),
            bbox.yMinimum(),
            bbox.xMaximum(),
            bbox.yMaximum(),
            tiles.LEVEL,
        ):
            ring = cell.boundary()
            lngs = [p[0] for p in ring]
            crosses_antimeridian = max(lngs) - min(lngs) > 180
            outline = QgsGeometry.fromPolygonXY(
                [[QgsPointXY(x, y) for x, y in ring]]
            )
            if crosses_antimeridian or outline.intersects(area):
                found.append(cell)
        return found

    def processAlgorithm(self, parameters, context, feedback):
        area, is_rect = self._area(parameters, context)
        mode = self.parameterAsEnum(parameters, self.GEOMETRY, context)
        min_conf = self.parameterAsDouble(
            parameters, self.MIN_CONFIDENCE, context
        )
        max_bytes = (
            self.parameterAsInt(parameters, self.MAX_DOWNLOAD_MB, context)
            * 1e6
        )
        # Polygon tiles also carry the centroid, so "both" needs one download.
        kind = 'points' if mode == POINTS else 'polygons'
        cache = cache_dir()

        cells = self._cells(area)
        feedback.pushInfo(
            tr('Area touches {} tile(s). Cache: {}').format(len(cells), cache)
        )
        todo, new_bytes = [], 0
        for cell in cells:
            if feedback.isCanceled():
                return {}
            path = tiles.cache_path(cache, kind, cell.token)
            if os.path.exists(path):
                feedback.pushInfo(tr('Tile {}: cached').format(cell.token))
                todo.append(cell.token)
                continue
            try:
                size = tiles.remote_size(kind, cell.token)
            except tiles.DownloadError as e:
                raise QgsProcessingException(
                    tr('Cannot reach Open Buildings: {}').format(e)
                )
            if size is None:
                feedback.pushInfo(
                    tr('Tile {}: no buildings in Open Buildings').format(
                        cell.token
                    )
                )
                continue
            feedback.pushInfo(
                tr('Tile {}: {:.1f} MB to download').format(
                    cell.token, size / 1e6
                )
            )
            todo.append(cell.token)
            new_bytes += size
        if not todo:
            raise QgsProcessingException(
                tr(
                    'Open Buildings has no data here. It covers Africa, '
                    'South and Southeast Asia, Latin America and the '
                    'Caribbean.'
                )
            )
        if new_bytes > max_bytes:
            raise QgsProcessingException(
                tr(
                    'This area needs {:.0f} MB of new downloads, over the '
                    '{:.0f} MB limit. Use a smaller area or raise the limit.'
                ).format(new_bytes / 1e6, max_bytes / 1e6)
            )

        fields = QgsFields()
        fields.append(QgsField('confidence', QMetaType.Type.Double))
        fields.append(QgsField('area_in_meters', QMetaType.Type.Double))
        fields.append(QgsField('full_plus_code', QMetaType.Type.QString))
        results = {}
        poly_sink = point_sink = None
        if mode in (POLYGONS, BOTH):
            poly_sink, results[self.OUTPUT_POLYGONS] = self.parameterAsSink(
                parameters,
                self.OUTPUT_POLYGONS,
                context,
                fields,
                Qgis.WkbType.Polygon,
                WGS84,
            )
            if poly_sink is None:
                raise QgsProcessingException(
                    tr('Set the building polygons output.')
                )
        if mode in (POINTS, BOTH):
            point_sink, results[self.OUTPUT_POINTS] = self.parameterAsSink(
                parameters,
                self.OUTPUT_POINTS,
                context,
                fields,
                Qgis.WkbType.Point,
                WGS84,
            )
            if point_sink is None:
                raise QgsProcessingException(
                    tr('Set the building points output.')
                )
        for dest in results.values():
            if context.willLoadLayerOnCompletion(dest):
                context.layerToLoadOnCompletionDetails(dest).setPostProcessor(
                    CONFIDENCE_STYLE
                )

        bbox = area.boundingBox()
        xmin, ymin, xmax, ymax = (
            bbox.xMinimum(),
            bbox.yMinimum(),
            bbox.xMaximum(),
            bbox.yMaximum(),
        )
        engine = None
        if not is_rect:
            engine = QgsGeometry.createGeometryEngine(area.constGet())
            engine.prepareGeometry()
        plus_code_col = 4 if kind == 'points' else 5
        fast = QgsFeatureSink.Flag.FastInsert
        kept = 0
        step = 100.0 / len(todo)

        for n, tok in enumerate(todo):
            base = n * step

            def on_download(done, total):
                if total:
                    feedback.setProgress(base + step * 0.5 * done / total)

            def on_read(fraction):
                feedback.setProgress(base + step * (0.5 + 0.5 * fraction))

            feedback.setProgressText(
                tr('Tile {} of {} ({})').format(n + 1, len(todo), tok)
            )
            try:
                path = tiles.download(
                    kind, tok, cache, on_download, feedback.isCanceled
                )
            except tiles.Canceled:
                return {}
            except tiles.DownloadError as e:
                raise QgsProcessingException(
                    tr('Download failed: {}').format(e)
                )
            tile_kept = 0
            for row in tiles.rows(path, on_read):
                if feedback.isCanceled():
                    return {}
                lat, lng, conf = float(row[0]), float(row[1]), float(row[3])
                if conf < min_conf or not (
                    xmin <= lng <= xmax and ymin <= lat <= ymax
                ):
                    continue
                point = QgsGeometry.fromPointXY(QgsPointXY(lng, lat))
                if engine is not None and not engine.contains(
                    point.constGet()
                ):
                    continue
                attrs = [conf, float(row[2]), row[plus_code_col]]
                if poly_sink is not None:
                    f = QgsFeature(fields)
                    f.setGeometry(QgsGeometry.fromWkt(row[4]))
                    f.setAttributes(attrs)
                    poly_sink.addFeature(f, fast)
                if point_sink is not None:
                    f = QgsFeature(fields)
                    f.setGeometry(point)
                    f.setAttributes(attrs)
                    point_sink.addFeature(f, fast)
                tile_kept += 1
            feedback.pushInfo(
                tr('Tile {}: {} building(s) kept').format(tok, tile_kept)
            )
            kept += tile_kept

        feedback.pushInfo(tr('{} building(s) in total').format(kept))
        results['COUNT'] = kept
        return results
