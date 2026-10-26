def classFactory(iface):
    from .plugin import OpenBuildingsPlugin

    return OpenBuildingsPlugin(iface)
