"""Runs inside Blender (invoked headlessly by export.py) to render one
.blend asset's isometric camera set and write its JSON manifest.

Not meant to be run directly — see render_blend() in export.py.

Scene conventions:
  - All mesh objects (i.e. everything except Empties/Cameras/Lights) are
    combined into one world-space bounding box, in Blender's +X (east) /
    +Y (north) / +Z (up) axes.
  - Every rendered direction/camera becomes an entry in the manifest's
    [views] table, keyed by its own direction label or camera object name.
    Each view has "image"/"render_width_px"/"render_height_px" plus its own
    "anchors" table — one entry per Empty in the scene, keyed by its own
    object name, giving that Empty's position within *this* view's rendered
    frame. This is per-view rather than a single shared value because a
    given world position lands somewhere different in each camera's own
    frame — a custom camera in particular may not share the standard
    directions' projection convention at all. Each anchor entry has:
      - "offset": the Empty's position within the view's rendered frame,
        normalized to [-0.5, 0.5] on each axis (0 at the frame's center,
        -0.5/0.5 at its edges; rounded to 4 decimal places). A consuming
        engine multiplies it directly by that view's own sprite size to get
        the pixel offset from the sprite's center.
      - "visible": true if the anchor has line of sight to that view's
        camera, from a ray cast against the scene — false means scene
        geometry occludes the anchor in that particular view, which a 2D
        engine can use to draw the anchor's overlay behind the sprite
        instead of in front of it.
  - Four standard 45°-projection directions are rendered: NE, NW, SE, SW
    (compass azimuth in the Blender XY plane, +Y = north). If the scene
    already has a Camera object named after one of those (case-insensitive),
    its own transform/lens/ortho/resolution settings are used as-is — full
    artist control. Any standard direction with no matching camera gets one
    created here: positioned on the corresponding compass diagonal, pitched
    down by --pitch (true isometric, ~35.264°, by default), framed
    orthographically to exactly fit the bounding box.
  - Any OTHER Camera object in the scene (any name that isn't NE/NW/SE/SW)
    is also rendered, as an extra view keyed by its own object name — this
    is how you add a custom shot (an icon/portrait camera, say) alongside
    the 4 standard directions. Extra cameras are always rendered with their
    own settings, same as an explicitly-named standard camera.
  - For auto-generated cameras, render resolution is derived from the
    fitted frame × png_px_per_unit. For artist-placed cameras (standard or
    extra), the scene's existing render resolution is used as-is, since
    their framing isn't ours to reinterpret.

Usage:
  blender <asset>.blend --background --python blender_scene_export.py -- \\
      <out_dir> <px_per_unit> <png_px_per_unit> <pitch_deg>
"""

import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

STANDARD_DIRECTIONS = {
    "NE": Vector((1, 1, 0)),
    "NW": Vector((-1, 1, 0)),
    "SW": Vector((-1, -1, 0)),
    "SE": Vector((1, -1, 0)),
}


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sanitize_name(name: str) -> str:
    """Normalizes a camera or Empty name for use as a manifest key."""
    return name.lower()


def world_bounds(objects):
    bbox_min = Vector((float("inf"),) * 3)
    bbox_max = Vector((float("-inf"),) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            bbox_min = Vector(min(a, b) for a, b in zip(bbox_min, world))
            bbox_max = Vector(max(a, b) for a, b in zip(bbox_max, world))
    return bbox_min, bbox_max


def bbox_corners(bbox_min, bbox_max):
    xs, ys, zs = (bbox_min.x, bbox_max.x), (bbox_min.y, bbox_max.y), (bbox_min.z, bbox_max.z)
    return [Vector((x, y, z)) for x in xs for y in ys for z in zs]


def spawn_iso_camera(scene, label, azimuth, center, pitch_deg, distance):
    cam_data = bpy.data.cameras.new(f"gen_{label}")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.01
    cam_data.clip_end = max(1000.0, distance * 2)
    cam_obj = bpy.data.objects.new(f"gen_{label}", cam_data)
    scene.collection.objects.link(cam_obj)

    pitch = math.radians(pitch_deg)
    horiz = azimuth.normalized() * math.cos(pitch)
    cam_dir = Vector((horiz.x, horiz.y, math.sin(pitch))).normalized()
    cam_obj.location = center + cam_dir * distance
    cam_obj.rotation_euler = (center - cam_obj.location).normalized().to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    return cam_obj


def fit_ortho_frame(cam_obj, corners, margin=1.02):
    """Sets ortho_scale so the camera's horizontal axis exactly frames
    `corners`, and returns (span_x, span_y) in world units for sizing the
    render resolution."""
    mat_inv = cam_obj.matrix_world.inverted()
    local = [mat_inv @ c for c in corners]
    xs, ys = [p.x for p in local], [p.y for p in local]
    span_x = (max(xs) - min(xs)) * margin
    span_y = (max(ys) - min(ys)) * margin
    cam_obj.data.sensor_fit = "HORIZONTAL"
    cam_obj.data.ortho_scale = span_x
    return span_x, span_y


def anchor_offset(scene, cam_obj, target):
    """[-0.5, 0.5] position of `target` within `cam_obj`'s rendered frame —
    using the scene's *current* render resolution, so call this only while
    that resolution matches `cam_obj`'s own — with 0 at the frame center
    and -0.5/0.5 at its edges. Computed via the camera's actual projection
    (ortho or perspective, whatever `cam_obj` is), so it's correct for any
    camera rather than assuming every view shares one screen convention."""
    ndc = world_to_camera_view(scene, cam_obj, target)
    return [round(ndc.x - 0.5, 4), round(ndc.y - 0.5, 4)]


def anchor_visible(scene, depsgraph, cam_obj, target, eps=1e-4):
    """True if `target` has line of sight to `cam_obj`, i.e. nothing in the
    scene occludes it along the same ray the renderer would trace for that
    camera. Orthographic cameras trace parallel rays (constant local X/Y,
    not converging on the camera origin), so the ray is built in the
    camera's local space rather than by aiming at its world position."""
    mat = cam_obj.matrix_world
    if cam_obj.data.type == "ORTHO":
        local_target = mat.inverted() @ target
        origin = mat @ Vector((local_target.x, local_target.y, 0.0))
        depth = -local_target.z
    else:
        origin = mat.translation
        depth = (target - origin).length
    if depth <= eps:
        return True
    direction = (target - origin).normalized()
    hit, *_ = scene.ray_cast(depsgraph, origin, direction, distance=depth - eps)
    return not hit


def render_camera(scene, cam_obj, out_png, resolution_x, resolution_y):
    scene.camera = cam_obj
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(out_png)
    bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) != 4:
        die("expected args: <out_dir> <px_per_unit> <png_px_per_unit> <pitch_deg>")
    out_dir, px_per_unit, png_px_per_unit, pitch_deg = argv
    px_per_unit = float(px_per_unit)
    png_px_per_unit = float(png_px_per_unit)
    pitch_deg = float(pitch_deg)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(bpy.data.filepath).stem

    scene = bpy.context.scene
    mesh_objs = [o for o in scene.objects if o.type not in ("EMPTY", "CAMERA", "LIGHT")]
    if not mesh_objs:
        die(f"no mesh objects found in {bpy.data.filepath}")

    bbox_min, bbox_max = world_bounds(mesh_objs)
    center = (bbox_min + bbox_max) / 2
    size = bbox_max - bbox_min
    corners = bbox_corners(bbox_min, bbox_max)
    distance = max(size.length, 1.0) * 4

    empties = [o for o in scene.objects if o.type == "EMPTY"]

    all_cams = [o for o in scene.objects if o.type == "CAMERA"]
    standard_cams = {}
    for label in STANDARD_DIRECTIONS:
        match = next((o for o in all_cams if o.name.upper() == label), None)
        if match:
            standard_cams[label] = match
    extra_cams = [o for o in all_cams if o not in standard_cams.values()]

    standard_render = {}
    for label, azimuth in STANDARD_DIRECTIONS.items():
        cam_obj = standard_cams.get(label)
        if cam_obj is None:
            cam_obj = spawn_iso_camera(scene, label, azimuth, center, pitch_deg, distance)
            span_x, span_y = fit_ortho_frame(cam_obj, corners)
            res_x = max(1, round(span_x * png_px_per_unit))
            res_y = max(1, round(span_y * png_px_per_unit))
        else:
            res_x, res_y = scene.render.resolution_x, scene.render.resolution_y
        standard_render[sanitize_name(label)] = (cam_obj, res_x, res_y)

    extra_render = {}
    for cam_obj in extra_cams:
        res_x, res_y = scene.render.resolution_x, scene.render.resolution_y
        extra_render[sanitize_name(cam_obj.name)] = (cam_obj, res_x, res_y)

    depsgraph = bpy.context.evaluated_depsgraph_get()

    def anchors_for(cam_obj):
        result = {}
        for empty in empties:
            pos = empty.matrix_world.translation
            result[sanitize_name(empty.name)] = {
                "offset": anchor_offset(scene, cam_obj, pos),
                "visible": anchor_visible(scene, depsgraph, cam_obj, pos),
            }
        return result

    views = {}
    for key, (cam_obj, res_x, res_y) in {**standard_render, **extra_render}.items():
        out_png = out_dir / f"{stem}_{key}.png"
        render_camera(scene, cam_obj, out_png, res_x, res_y)
        views[key] = {
            "image": out_png.name,
            "render_width_px": res_x,
            "render_height_px": res_y,
            "anchors": anchors_for(cam_obj),
        }
        print(f"rendered {out_png.name}: {res_x}x{res_y}")

    manifest = {
        "schema_version": 1,
        "asset": {
            "name": stem,
            "source": Path(bpy.data.filepath).name,
            "px_per_unit": px_per_unit,
            "bbox_size": [size.x, size.y, size.z],
        },
        "views": views,
    }
    out_json = out_dir / f"{stem}.json"
    with out_json.open("w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
