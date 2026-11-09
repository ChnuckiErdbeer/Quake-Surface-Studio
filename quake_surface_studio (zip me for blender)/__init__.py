bl_info = {
    "name": "Quake Surface Studio",
    "author": "OpenAI",
    "version": (0, 17, 2),
    "blender": (3, 6, 0),
    "location": "Quake Studio workspace",
    "description": "Dedicated Quake BSP editing workspace with viewport tools, lighting and engine integration",
    "category": "Import-Export",
}

from . import addon


def register():
    addon.register()


def unregister():
    addon.unregister()
