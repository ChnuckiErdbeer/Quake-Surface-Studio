bl_info = {
    "name": "Quake Surface Studio",
    "author": "OpenAI",
    "version": (0, 18, 3),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Quake",
    "description": "Quake BSP editing, lighting, map audits and engine integration",
    "category": "Import-Export",
}

from . import addon


def register():
    addon.register()


def unregister():
    addon.unregister()
