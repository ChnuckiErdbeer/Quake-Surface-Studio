"""Small, Blender-independent helpers for classifying light node trees."""

def _node_kind(node):
    value = getattr(node, "bl_idname", "") or getattr(node, "type", "")
    return str(value)


def _approximately_equal(value, expected, tolerance=1e-6):
    try:
        actual = tuple(float(component) for component in value)
    except TypeError:
        try:
            actual = (float(value),)
        except (TypeError, ValueError, OverflowError):
            return False
    except (ValueError, OverflowError):
        return False

    expected = tuple(float(component) for component in expected)
    if len(actual) != len(expected):
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def is_default_light_node_tree(light_data):
    """True for a new/empty light tree or Blender's untouched default graph.

    Blender 5.1+ creates a simple Emission -> Light Output graph for new lights
    and always reports Light.use_nodes=True. That default graph is equivalent
    to the normal light settings, so QSS may replace it with its own falloff
    graph. Any modified or more complex graph is treated as user-authored.
    """
    tree = getattr(light_data, "node_tree", None)
    if tree is None:
        return True

    try:
        nodes = list(tree.nodes)
    except (AttributeError, TypeError):
        return False
    if not nodes:
        return True
    if len(nodes) != 2:
        return False

    emission_nodes = [
        node for node in nodes
        if _node_kind(node) in {"ShaderNodeEmission", "EMISSION"}
    ]
    output_nodes = [
        node for node in nodes
        if _node_kind(node) in {"ShaderNodeOutputLight", "OUTPUT_LIGHT"}
    ]
    if len(emission_nodes) != 1 or len(output_nodes) != 1:
        return False

    emission = emission_nodes[0]
    output = output_nodes[0]
    inputs = getattr(emission, "inputs", None)
    try:
        color_socket = inputs.get("Color")
        strength_socket = inputs.get("Strength")
    except AttributeError:
        return False
    if color_socket is None or strength_socket is None:
        return False
    color_value = getattr(color_socket, "default_value", None)
    strength_value = getattr(strength_socket, "default_value", None)
    if not _approximately_equal(color_value, (1.0, 1.0, 1.0, 1.0)):
        # Some supported Blender versions expose the color socket as RGB.
        if not _approximately_equal(color_value, (1.0, 1.0, 1.0)):
            return False
    if not _approximately_equal(strength_value, (1.0,)):
        return False

    target = str(getattr(output, "target", "ALL"))
    if target not in {"ALL", "CYCLES"}:
        return False

    try:
        links = list(tree.links)
    except (AttributeError, TypeError):
        return False
    if len(links) != 1:
        return False
    link = links[0]
    if getattr(link, "from_node", None) is not emission:
        return False
    if getattr(link, "to_node", None) is not output:
        return False
    if getattr(getattr(link, "from_socket", None), "name", "") != "Emission":
        return False
    if getattr(getattr(link, "to_socket", None), "name", "") != "Surface":
        return False
    if bool(getattr(emission, "mute", False)) or bool(getattr(output, "mute", False)):
        return False
    return True
  
  
def is_safe_to_replace_light_node_tree(light_data, qss_created_by_current_import=False):
    """True when QSS may replace a light's current shader tree.

    A light datablock created by the current BSP import is known to contain
    Blender-generated starter nodes, not user-authored nodes. This one-shot
    import permission is deliberately explicit; later updates must pass the
    normal default-tree classifier so genuine user edits remain protected.
    """
    if qss_created_by_current_import:
        return True
    return is_default_light_node_tree(light_data)
