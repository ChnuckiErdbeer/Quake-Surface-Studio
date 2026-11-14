bl_info = {
    "name": "SLOPGATE",
    "author": "OpenAI",
    "version": (0, 21, 9),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > SLOPGATE",
    "description": "Quake BSP editing, texture painting, lighting, map audits and engine integration",
    "category": "Import-Export",
}

from . import addon


def register():
    addon.register()


def unregister():
    addon.unregister()
