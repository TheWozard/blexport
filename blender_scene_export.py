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
  - Every view is also rendered a second time with every object's material
    overridden (bpy ViewLayer.material_override) to a Material named
    "normals" (case-insensitive), producing a "*_normal.png" alongside that
    view's regular image and a "normal_image" key in its manifest entry.
    If the asset's own scene has such a material, that one is used —
    otherwise one is linked in automatically from SHARED_MATERIALS_BLEND
    (see ensure_normals_material()), so assets get normal maps for free
    without each one needing its own copy. Add a "normals" material
    directly to a specific asset only if it needs its own custom bake;
    otherwise edit SHARED_MATERIALS_BLEND once and every asset picks it up.
    That material's shader graph is what defines the bake: Geometry Normal
    -> Vector Transform (World to Camera) -> encode to [0,1] -> Emission,
    so the render captures each view's surface normal in that view's own
    screen space (+X right, +Y up, +Z toward the viewer) instead of the
    object's real appearance. Blender's Vector Transform node negates Z
    relative to the camera object's own local axes (X/Y match the camera's
    right/up exactly; verified empirically, not documented anywhere) — the
    graph in SHARED_MATERIALS_BLEND multiplies by (1, 1, -1) right after
    the Vector Transform to flip it back to "+Z toward the viewer" before
    encoding. Preserve that flip if you ever rebuild the graph from scratch.
    If neither the asset nor the shared file has a "normals" material, no
    normal maps are rendered for that asset.
    The normal-map render forces the scene's view transform to "Raw" for
    that one render — the encoded [0,1] values are data, not a color to be
    graded, so the artist's AgX/Filmic/etc. look (which is nonlinear and
    would distort them, e.g. skewing hues and shrinking decoded vectors to
    sub-unit length) must not touch them. The color pass is unaffected.
  - For auto-generated cameras, render resolution is derived from the
    fitted frame × png_px_per_unit. For artist-placed cameras (standard or
    extra), the scene's existing render resolution is used as-is, since
    their framing isn't ours to reinterpret.
  - A .blend file can hold multiple independent assets as sibling
    Collections directly under the scene's root collection (Collection >
    New Collection in the Outliner, not nested inside one another). With
    2+ such collections, each is rendered as its own asset — its own
    bounding box, standard directions, extra cameras, and anchors, scoped
    to just the objects in that collection (recursively, via
    Collection.all_objects) — and the manifest becomes schema v2:
    {schema_version: 2, assets: {<collection>: {asset, views}, ...}}
    keyed by sanitize_name(collection.name), with image filenames
    "<stem>_<collection>_<view>.png" to keep them from colliding. Every
    *other* top-level collection is hidden from render (Collection.hide_
    render) while each one's views are rendered, so one asset's geometry
    never bleeds into another's frame — put shared scene furniture (e.g. a
    single sun light meant to illuminate every asset) directly in the
    scene's root collection, outside any of the per-asset collections, so
    it's never toggled off. With 0 or 1 top-level collections, none of
    this applies — the whole scene is one asset, exactly as if this
    feature didn't exist: schema v1, "<stem>_<view>.png" filenames, same
    as always. This is what makes the feature backward compatible: a
    scene that happens to keep everything in a single habitual collection
    (a common Blender authoring habit unrelated to wanting multiple
    exported assets) is unaffected.
  - An asset's objects can need to render both in front of AND behind some
    of its own other geometry at once — e.g. glasses whose temple arm tucks
    behind the ear while the lenses sit in front of the face — which a
    single flat sprite can't represent. Flip an object's own "Holdout"
    visibility flag on in the Object Properties panel (bpy: Object.is_
    holdout) to opt that asset into an automatic front/back split. "image"
    keeps its usual meaning and is always present — a normal render with
    the holdout object(s) hidden entirely, i.e. the complete, unoccluded
    view of everything else — but a view where those objects actually
    occlude something also gets an "overlay_image": just the part nearer
    to camera than the holdout object(s) (a per-pixel cutout via Object.
    is_holdout toggled True for that one render, using Blender's own
    Z-test rather than a depth buffer or compositor graph of our own),
    meant to be drawn again on top of whatever the consuming engine draws
    in between "image" and it (e.g. the holdout object's own real
    on-screen representation) so that part isn't lost to the occlusion. A
    consuming engine draws, in fixed order: image -> [whatever occupies
    the holdout's own space] -> overlay_image (if present). Any number of
    objects can have the Holdout flag set; all of them are used together.
    Holdout objects are never themselves rendered as color — they exist
    purely to cut the hole, and the export script only ever reads the flag
    (never sets it permanently). See split_front_back() for the mechanism,
    including why layering the overlay directly onto the same complete
    "image" (rather than computing two complementary alpha masks that
    together must reconstruct full coverage, as an earlier version of this
    tool did) avoids a faint seam along the cutout's antialiased edge. An
    asset with no holdout-flagged object is unaffected by any of this — no
    "overlay_image" ever appears, same as always. Holdout objects still
    count toward the asset's own bounding box (see above), same as any
    other mesh object, so author them to match the size/position of
    whatever they represent (e.g. a stand-in copy of a head an accessory
    sits on) if you want the frame sized/positioned to match it. Each
    asset (top-level collection, or the whole scene with 0/1 of them) is
    scanned for its own holdout-flagged objects independently of every
    other asset's — there's no cross-collection reference or shared camera
    involved.

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

SHARED_MATERIALS_BLEND = Path(__file__).parent / "shared_materials.blend"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def sanitize_name(name: str) -> str:
    """Normalizes a camera or Empty name for use as a manifest key."""
    return name.lower()


def find_material(name: str):
    """Case-insensitive lookup of a Material by name, or None."""
    return next((m for m in bpy.data.materials if m.name.lower() == name.lower()), None)


def ensure_normals_material():
    """The asset's own "normals" material if it has one; otherwise one
    appended from SHARED_MATERIALS_BLEND, so assets need not each carry
    their own copy of the normal-map bake. None if neither has one."""
    mat = find_material("normals")
    if mat is not None or not SHARED_MATERIALS_BLEND.exists():
        return mat
    with bpy.data.libraries.load(str(SHARED_MATERIALS_BLEND), link=False) as (data_from, data_to):
        if "normals" not in data_from.materials:
            return None
        data_to.materials = ["normals"]
    return data_to.materials[0]


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


def set_holdout(objects, value):
    for obj in objects:
        obj.is_holdout = value


def split_front_back(scene, cam_obj, image_png, overlay_png, res_x, res_y, base_objects, alpha_eps=1e-3):
    """Renders this view against `base_objects` (see the module docstring's
    front/back-split section). `image_png` gets a normal render with
    `base_objects` hidden entirely — the complete, unoccluded render of
    everything else, always correct and meant to be drawn first regardless
    of occlusion. `overlay_png` gets a second render with `base_objects`
    visible but flagged Object.is_holdout (a per-pixel cutout wherever
    they're nearer to camera, using Blender's own Z-test rather than a
    depth buffer or compositor graph of our own) — just the part nearer
    than `base_objects`, meant to be drawn again on top of whatever the
    consuming engine draws in between (e.g. `base_objects`'s own on-screen
    representation), so that part isn't lost to the occlusion.

    Returns True if `overlay_png` is actually needed for this view — some
    pixel really is occluded by `base_objects` — and False if nothing in
    the frame sits behind them at all, in which case `overlay_png` is
    deleted; the caller should drop the "overlay_image" key entirely rather
    than point at a redundant, identical file.

    Compositing the overlay directly on top of the same complete
    `image_png` (rather than computing two complementary alpha masks that
    must together reconstruct full coverage, as an earlier version of this
    function did) avoids a double-transparency seam along the cutout's
    antialiased edge: `image_png` already has full/correct alpha wherever
    it's genuinely opaque, so alpha-compositing any fractional-alpha
    overlay of the same underlying color on top can't reduce coverage below
    1 there — whereas summing two independently-antialiased partial-alpha
    layers falls just short of 1 right at the boundary, showing up as a
    faint seam."""
    original_hide = [(obj, obj.hide_render) for obj in base_objects]
    for obj in base_objects:
        obj.hide_render = True
    render_camera(scene, cam_obj, image_png, res_x, res_y)

    for obj, _ in original_hide:
        obj.hide_render = False
    set_holdout(base_objects, True)
    render_camera(scene, cam_obj, overlay_png, res_x, res_y)
    set_holdout(base_objects, False)
    for obj, hide_render in original_hide:
        obj.hide_render = hide_render

    image_img = bpy.data.images.load(str(image_png))
    overlay_img = bpy.data.images.load(str(overlay_png))
    image_alpha = image_img.pixels[3::4]
    overlay_alpha = overlay_img.pixels[3::4]
    needed = any(a - b > alpha_eps for a, b in zip(image_alpha, overlay_alpha))
    bpy.data.images.remove(image_img)
    bpy.data.images.remove(overlay_img)

    if not needed:
        overlay_png.unlink()
    return needed


def compute_camera_set(scene, objects, bbox_min, bbox_max, pitch_deg, png_px_per_unit):
    """Matches/creates the standard-direction and extra cameras for
    `objects`'s bounding box. Returns a dict of view key -> (cam_obj,
    res_x, res_y), covering both standard directions and extra cameras."""
    center = (bbox_min + bbox_max) / 2
    corners = bbox_corners(bbox_min, bbox_max)
    distance = max((bbox_max - bbox_min).length, 1.0) * 4

    all_cams = [o for o in objects if o.type == "CAMERA"]
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

    return {**standard_render, **extra_render}


def render_views(scene, out_dir, name_prefix, camera_set, empties, base_objects=None):
    """Renders each view in `camera_set` (key -> (cam_obj, res_x, res_y)),
    writing "<name_prefix>_<view>[_normal].png" files, and returns this
    asset's `views` manifest dict. If `base_objects` is given (this asset's
    own objects with Object.is_holdout set), "image" always renders as the
    complete view (those objects hidden entirely) and views where they
    actually occlude something also get an "overlay_image" (see
    split_front_back() and the module docstring's front/back-split
    section)."""
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

    normals_material = ensure_normals_material()
    view_layer = bpy.context.view_layer

    views = {}
    for key, (cam_obj, res_x, res_y) in camera_set.items():
        out_png = out_dir / f"{name_prefix}_{key}.png"
        overlay_needed = False
        if base_objects is None:
            render_camera(scene, cam_obj, out_png, res_x, res_y)
        else:
            out_overlay_png = out_dir / f"{name_prefix}_{key}_overlay.png"
            overlay_needed = split_front_back(scene, cam_obj, out_png, out_overlay_png, res_x, res_y, base_objects)

        view = {
            "image": out_png.name,
            "render_width_px": res_x,
            "render_height_px": res_y,
            "anchors": anchors_for(cam_obj),
        }
        if overlay_needed:
            view["overlay_image"] = out_overlay_png.name
        print(f"rendered {out_png.name}: {res_x}x{res_y}")

        if normals_material is not None:
            out_normal_png = out_dir / f"{name_prefix}_{key}_normal.png"
            view_layer.material_override = normals_material
            view_transform = scene.view_settings.view_transform
            scene.view_settings.view_transform = "Raw"
            if base_objects is None:
                render_camera(scene, cam_obj, out_normal_png, res_x, res_y)
            else:
                original_hide = [(obj, obj.hide_render) for obj in base_objects]
                for obj in base_objects:
                    obj.hide_render = True
                render_camera(scene, cam_obj, out_normal_png, res_x, res_y)
                for obj, hide_render in original_hide:
                    obj.hide_render = hide_render
            scene.view_settings.view_transform = view_transform
            view_layer.material_override = None
            view["normal_image"] = out_normal_png.name
            print(f"rendered {out_normal_png.name}: {res_x}x{res_y}")

        views[key] = view

    return views


def render_asset(scene, objects, out_dir, name_prefix, asset_name, px_per_unit, png_px_per_unit, pitch_deg):
    """Renders one asset's views (see render_views()) from `objects`.
    Returns this asset's {asset, views} manifest entry. Any object in
    `objects` with its own Object.is_holdout flag set (see the module
    docstring's front/back-split section) drives an automatic front/back
    split for every other object in this same asset."""
    mesh_objs = [o for o in objects if o.type not in ("EMPTY", "CAMERA", "LIGHT")]
    if not mesh_objs:
        die(f"no mesh objects found for asset {asset_name!r} in {bpy.data.filepath}")

    bbox_min, bbox_max = world_bounds(mesh_objs)
    size = bbox_max - bbox_min

    camera_set = compute_camera_set(scene, objects, bbox_min, bbox_max, pitch_deg, png_px_per_unit)

    empties = [o for o in objects if o.type == "EMPTY"]
    holdout_objs = [o for o in mesh_objs if o.is_holdout]
    views = render_views(scene, out_dir, name_prefix, camera_set, empties, base_objects=holdout_objs or None)

    asset = {
        "asset": {
            "name": asset_name,
            "source": Path(bpy.data.filepath).name,
            "px_per_unit": px_per_unit,
            "bbox_size": [size.x, size.y, size.z],
        },
        "views": views,
    }
    return asset


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
    collections = list(scene.collection.children)

    if len(collections) < 2:
        asset = render_asset(scene, scene.objects, out_dir, stem, stem, px_per_unit, png_px_per_unit, pitch_deg)
        manifest = {"schema_version": 1, **asset}
    else:
        assets = {}
        for coll in collections:
            asset_key = sanitize_name(coll.name)
            original_hide = {c: c.hide_render for c in collections}
            for c in collections:
                c.hide_render = c is not coll
            try:
                assets[asset_key] = render_asset(
                    scene, coll.all_objects, out_dir, f"{stem}_{asset_key}", asset_key,
                    px_per_unit, png_px_per_unit, pitch_deg,
                )
            finally:
                for c, hide_render in original_hide.items():
                    c.hide_render = hide_render

        manifest = {"schema_version": 2, "assets": assets}

    out_json = out_dir / f"{stem}.json"
    with out_json.open("w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
