from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsMarkerSymbol,
    QgsProcessingLayerPostProcessorInterface,
    QgsRuleBasedRenderer,
)

# Confidence bands as Google styles them in its Earth Engine example (lower
# bound inclusive), with orange in place of Google's yellow.
BANDS = [
    ('"confidence" >= 0.75', 'Confidence ≥ 0.75', '0,255,0'),
    (
        '"confidence" >= 0.70 AND "confidence" < 0.75',
        'Confidence 0.70 – 0.75',
        '255,140,0',
    ),
    (
        '"confidence" >= 0.65 AND "confidence" < 0.70',
        'Confidence 0.65 – 0.70',
        '255,0,0',
    ),
    ('"confidence" < 0.65', 'Confidence < 0.65', '158,158,158'),
]


def _symbol(geometry_type, rgb):
    if geometry_type == Qgis.GeometryType.Point:
        return QgsMarkerSymbol.createSimple(
            {
                'name': 'circle',
                'color': rgb,
                'size': '1.6',
                'outline_style': 'no',
            }
        )
    return QgsFillSymbol.createSimple(
        {'color': rgb + ',140', 'outline_color': rgb, 'outline_width': '0.2'}
    )


def confidence_renderer(geometry_type):
    root = QgsRuleBasedRenderer.Rule(None)
    for expression, label, rgb in BANDS:
        root.appendChild(
            QgsRuleBasedRenderer.Rule(
                _symbol(geometry_type, rgb), 0, 0, expression, label
            )
        )
    return QgsRuleBasedRenderer(root)


class ConfidenceStyle(QgsProcessingLayerPostProcessorInterface):
    def postProcessLayer(self, layer, context, feedback):
        layer.setRenderer(confidence_renderer(layer.geometryType()))
        layer.triggerRepaint()


# Processing keeps only a pointer to the post-processor, so it must outlive the
# algorithm run; one shared instance does.
CONFIDENCE_STYLE = ConfidenceStyle()
