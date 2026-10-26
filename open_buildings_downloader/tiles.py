"""Fetch and read Google Open Buildings v3 tiles.

One gzipped CSV per S2 level-6 cell."""

import csv
import gzip
import os
import sys

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

LEVEL = 6
BASE_URL = 'https://storage.googleapis.com/open-buildings-data/v3'
KINDS = {
    # kind: bucket folder. Polygon rows carry a WKT column; point rows do not.
    'polygons': 'polygons_s2_level_6_gzip_no_header',
    'points': 'points_s2_level_6_gzip_no_header',
}

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


class Canceled(Exception):
    pass


class DownloadError(Exception):
    pass


def url(kind, tok):
    return '%s/%s/%s_buildings.csv.gz' % (BASE_URL, KINDS[kind], tok)


def cache_path(cache_dir, kind, tok):
    return os.path.join(cache_dir, KINDS[kind], '%s_buildings.csv.gz' % tok)


def _request(kind, tok):
    # Tiles are cached on disk by the plugin; keep them out of QGIS's own
    # network cache, which is far too small for them.
    req = QNetworkRequest(QUrl(url(kind, tok)))
    req.setAttribute(
        QNetworkRequest.Attribute.CacheLoadControlAttribute,
        QNetworkRequest.CacheLoadControl.AlwaysNetwork,
    )
    req.setAttribute(
        QNetworkRequest.Attribute.CacheSaveControlAttribute, False
    )
    return req


def remote_size(kind, tok):
    """Size in bytes, or None when Google has no buildings in that cell."""
    blocking = QgsBlockingNetworkRequest()
    error = blocking.head(_request(kind, tok))
    reply = blocking.reply()
    if (
        reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        == 404
    ):
        return None
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise DownloadError(
            '%s: %s' % (url(kind, tok), blocking.errorMessage())
        )
    return int(bytes(reply.rawHeader(b'Content-Length')) or 0)


def download(kind, tok, cache_dir, on_progress, is_canceled):
    """Download a tile into the cache unless it is there; return its path.

    Goes through QGIS's network manager, so proxy and SSL settings apply, and
    streams to a .part file renamed at the end, so an interrupted download
    never leaves a truncated tile behind."""
    path = cache_path(cache_dir, kind, tok)
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + '.part'
    with open(part, 'wb') as out:
        reply = QgsNetworkAccessManager.instance().get(_request(kind, tok))
        loop = QEventLoop()

        def drain():
            if reply.isOpen():
                out.write(reply.readAll().data())

        def check_canceled():
            if is_canceled():
                reply.abort()

        reply.readyRead.connect(drain)
        reply.downloadProgress.connect(
            lambda done, total: on_progress(done, total if total > 0 else None)
        )
        reply.finished.connect(loop.quit)
        poll = QTimer()
        poll.timeout.connect(check_canceled)
        poll.start(250)
        loop.exec()
        poll.stop()
        drain()
        error, message = reply.error(), reply.errorString()
        reply.deleteLater()
    if is_canceled():
        os.remove(part)
        raise Canceled()
    if error != QNetworkReply.NetworkError.NoError:
        os.remove(part)
        raise DownloadError('%s: %s' % (url(kind, tok), message))
    os.replace(part, path)
    return path


def rows(path, on_progress):
    """Yield one list per building, reporting the share of the file read.

    polygons: [lat, lng, area_in_meters, confidence, wkt, full_plus_code]
    points:   [lat, lng, area_in_meters, confidence, full_plus_code]"""
    size = os.path.getsize(path) or 1
    with open(path, 'rb') as raw, gzip.open(raw, 'rt', newline='') as f:
        for n, row in enumerate(csv.reader(f)):
            if n % 20000 == 0:
                on_progress(raw.tell() / size)
            yield row
