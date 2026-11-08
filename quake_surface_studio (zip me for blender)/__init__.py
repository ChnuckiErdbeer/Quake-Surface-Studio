bl_info = {
    "name": "Quake Surface Studio",
    "author": "OpenAI",
    "version": (0, 11, 4),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Quake",
    "description": "Paint Quake BSP29 textures and lightmaps; preview entity lights and BSPX RGB lighting",
    "category": "Import-Export",
}

from . import addon


def register():
    addon.register()


def unregister():
    addon.unregister()
