bl_info = {
    "name": "Slipgate",
    "author": "OpenAI",
    "version": (0, 20, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Slipgate",
    "description": "Quake BSP editing, texture painting, lighting, map audits and engine integration",
    "category": "Import-Export",
}

from . import addon


def register():
    addon.register()


def unregister():
    addon.unregister()
