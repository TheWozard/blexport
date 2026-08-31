# blender_export

Renders `.blend` game assets into per-direction PNGs plus a JSON manifest, for a 45°-projection (isometric) game. Standalone and project-agnostic — point it at a directory of `.blend` files, get PNGs + `.json` manifests back.

## Requirements

- Python 3.9+ (stdlib only — no pip installs needed)
- [Blender](https://www.blender.org/download/) on `PATH` (`brew install --cask blender`)

## Usage

```sh
python3 export.py assets/                # render every stale .blend under assets/
python3 export.py assets/hero.blend      # render a single asset
python3 export.py assets/ --force        # re-render even if up to date
python3 export.py assets/ --out renders/ # write output elsewhere instead of alongside each .blend
```

Output is written alongside each source `.blend` by default:

```
assets/hero.blend
assets/hero.json       ← manifest
assets/hero_ne.png
assets/hero_nw.png
assets/hero_se.png
assets/hero_sw.png
```

Re-running skips any `.blend` whose manifest is newer than the source file — pass `--force` to override.

## Scene conventions

- **Geometry** — everything in the scene except Empties, Cameras, and Lights is combined into one world-space bounding box. That box is what the four standard cameras frame.
- **Anchors** — every Empty in the scene becomes a named anchor point, keyed by its own object name (e.g. `center`, `head`, or anything else you add), nested under each view's own `anchors` table (not shared globally), since a given world position lands somewhere different in each camera's own frame — a custom camera in particular may not share the standard directions' projection convention at all. Each entry has an `offset` — the anchor's position within that view's rendered frame, normalized to `[-0.5, 0.5]` on each axis (`0` at the frame's center, `-0.5`/`0.5` at its edges; rounded to 4 decimal places), computed from that view's actual camera projection so a consuming engine can multiply it directly by that view's own sprite size to get the pixel offset from the sprite's center — and a `visible` bool, from a line-of-sight ray cast from that view's camera to the anchor, where `false` means scene geometry occludes it in that particular view (a 2D engine can use this to draw the anchor's overlay behind the sprite instead of in front of it).
- **Standard directions (NE / NW / SE / SW)** — compass azimuth in the Blender XY plane (`+Y` = north, `+X` = east). If the scene already has a Camera object named `NE`, `NW`, `SE`, or `SW` (case-insensitive), that camera's own transform, lens, ortho scale, and resolution are used exactly as authored. Any of the four with no matching camera gets one created automatically: positioned on that compass diagonal, pitched down by `--pitch` below the horizon (default `35.264°`, true isometric), and orthographically framed to exactly fit the bounding box.
- **Extra cameras** — any other Camera object in the scene (any name besides NE/NW/SE/SW) is rendered too, as an extra frame keyed by its own object name — e.g. add a camera named `icon` for a portrait shot alongside the four directions. Extra cameras always use their own settings, the same as an explicitly-named standard camera.
- **Normal maps** — every view is rendered a second time with every object's material swapped to one named `normals` (case-insensitive), writing a `<view>_normal.png` next to that view's regular image and adding a `normal_image` key to its manifest entry. An asset's own scene can define this material for a custom bake; otherwise one is linked in automatically from `shared_materials.blend` (next to the scripts), so assets get normal maps for free without each needing a local copy — edit that file's `normals` material once to change the bake everywhere. Its shader graph outputs each surface's normal in *that view's own screen space* — `+X` right, `+Y` up, `+Z` toward the viewer — via `Geometry > Normal` → `Vector Transform` (World → Camera) → **multiply by `(1, 1, -1)`** (Blender's Vector Transform node negates Z relative to the camera's own local axes — an empirically-verified quirk, not documented anywhere — so this flips it back) → multiply-add by `0.5`/`0.5` to map `[-1, 1]` into `[0, 1]` → `Emission` (unlit, so lighting doesn't distort the encoded values). The render also forces the scene's view transform to `Raw` for that one pass, since the encoded values are data, not a color to be graded by AgX/Filmic/etc. If neither the asset nor the shared file has a `normals` material, no normal maps get rendered for that asset.
- **Render setup** — transparent film and PNG/RGBA output are always enforced by the script. For auto-generated cameras, resolution is derived from the fitted frame × (`--px-per-unit` × `--supersample`). For artist-placed cameras (standard or extra), the scene's existing render resolution (`Output Properties → Resolution`) is used as-is — their framing isn't ours to reinterpret.
- **Multiple assets per file** — put 2 or more independent assets in one `.blend` as sibling Collections directly under the scene's root collection (Blender's default "Scene Collection" — not nested inside each other). Each becomes its own asset: its own bounding box, standard directions, extra cameras, and anchors, scoped to just the objects in that collection (recursively — sub-collections nested inside one count as part of it). Every *other* top-level collection is hidden from render while each one's views are rendered, so assets never bleed into each other's frame — keep shared scene furniture (e.g. one light meant to illuminate everything) directly in the root collection, outside any per-asset collection, so it's never hidden. With 0 or 1 top-level collections, none of this applies: the whole scene is a single asset, same as if this feature didn't exist. This is what keeps it backward compatible — a scene that happens to keep everything in one habitual collection (a common Blender habit, unrelated to wanting multiple exported assets) renders exactly as before.

## JSON manifest schema

### v1 — single asset per file (0 or 1 top-level collections)

```json
{
  "schema_version": 1,
  "asset": {
    "name": "hero",
    "source": "hero.blend",
    "px_per_unit": 32.0,
    "bbox_size": [1.0, 1.0, 2.0]
  },
  "views": {
    "ne": {
      "image": "hero_ne.png",
      "normal_image": "hero_ne_normal.png",
      "render_width_px": 640,
      "render_height_px": 640,
      "anchors": {
        "center": { "offset": [0.0, 0.42], "visible": true },
        "head": { "offset": [0.0, 0.49], "visible": true }
      }
    },
    "nw": {
      "image": "hero_nw.png",
      "render_width_px": 640,
      "render_height_px": 640,
      "anchors": {
        "center": { "offset": [0.01, 0.41], "visible": true },
        "head": { "offset": [0.0, 0.49], "visible": true }
      }
    },
    "se": {
      "image": "hero_se.png",
      "render_width_px": 640,
      "render_height_px": 640,
      "anchors": {
        "center": { "offset": [-0.02, 0.4], "visible": false },
        "head": { "offset": [0.0, 0.49], "visible": true }
      }
    },
    "sw": {
      "image": "hero_sw.png",
      "render_width_px": 640,
      "render_height_px": 640,
      "anchors": {
        "center": { "offset": [0.0, 0.42], "visible": false },
        "head": { "offset": [0.0, 0.49], "visible": true }
      }
    },
    "icon": {
      "image": "hero_icon.png",
      "render_width_px": 512,
      "render_height_px": 512,
      "anchors": {
        "center": { "offset": [0.1, 0.3], "visible": true },
        "head": { "offset": [0.0, 0.45], "visible": true }
      }
    }
  }
}
```

- `asset.bbox_size` is in Blender units: width (x), depth (y), height (z).
- `views.<key>` — one entry per rendered direction/camera, keyed by direction label (`ne`/`nw`/`se`/`sw`) or camera object name (e.g. `icon` above). Extra-camera views only appear when the scene has extra cameras. `normal_image` only appears when the scene has a `normals` material (see Scene conventions above).
- `views.<key>.anchors.<name>` — one entry per Empty in the scene, keyed by its name, giving that Empty's position within *this* view's rendered frame (see Scene conventions above for why offset varies per view).
- `render_width_px`/`render_height_px` are the actual PNG pixel dimensions — how large to draw a frame depends on the consuming engine's own scale convention, not something this tool assumes.

### v2 — multiple assets per file (2+ top-level collections)

```json
{
  "schema_version": 2,
  "assets": {
    "hero": {
      "asset": {
        "name": "hero",
        "source": "party.blend",
        "px_per_unit": 32.0,
        "bbox_size": [1.0, 1.0, 2.0]
      },
      "views": {
        "ne": {
          "image": "party_hero_ne.png",
          "normal_image": "party_hero_ne_normal.png",
          "render_width_px": 640,
          "render_height_px": 640,
          "anchors": {
            "head": { "offset": [0.0, 0.49], "visible": true }
          }
        }
      }
    },
    "shield": {
      "asset": {
        "name": "shield",
        "source": "party.blend",
        "px_per_unit": 32.0,
        "bbox_size": [0.6, 0.1, 0.6]
      },
      "views": {
        "ne": {
          "image": "party_shield_ne.png",
          "render_width_px": 320,
          "render_height_px": 320,
          "anchors": {}
        }
      }
    }
  }
}
```

Each entry under `assets.<collection>` has the exact same `asset`/`views` shape as the v1 manifest above — v2 just nests one of these per top-level collection, keyed by `sanitize_name(collection.name)`. Image filenames get the collection name spliced in (`<stem>_<collection>_<view>.png`) so the two assets' files never collide in the same output directory.

## Design notes / open assumptions

These were reasonable defaults picked without a real `.blend` file to test against — adjust freely if they don't match your project:

- **Camera pitch** defaults to true isometric (`35.264°`, `atan(1/√2)`). Common alternatives are `30°` (classic 2:1 "dimetric" pixel art) — pass `--pitch 30`.
- **`px_per_unit`** defaults to 32 (1 Blender unit = 1 tile = 32 display px), matching a common tile-based game convention — pass `--px-per-unit` to change it.
