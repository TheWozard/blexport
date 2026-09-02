# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A standalone, project-agnostic tool that renders `.blend` game assets into per-direction PNGs plus a JSON manifest, for a 45°-projection (isometric) game. Point it at a directory of `.blend` files, get PNGs + `.json` manifests back. Ships as a single static Go binary (`blexport`) — no runtime dependencies beyond a `blender` binary on `PATH`.

## Commands

Prefer the `just` recipes below over calling `go run .` / `find` directly — they're the intended entry points for this repo.

```sh
just export              # render every stale .blend under assets/ (default path="assets")
just export path/to/dir  # render a different directory or single .blend file
just force               # re-render assets/ even if manifests are up to date
just build                # build the blexport binary to ./blexport
just clean-backups       # delete Blender's *.blend1/.blend2/... backup files under assets/
just clean               # delete generated backups + *.json manifests + *.png renders under assets/ (keeps *.blend)
```

Equivalent raw invocation (`blexport export`'s own CLI, for flags not exposed via `just`):

```sh
go run . export assets/ --out renders/ --px-per-unit 32 --supersample 4 --pitch 35.264
```

`go build ./...`, `go vet ./...`, and `gofmt -l .` are the checks CI runs (`.github/workflows/ci.yml`). There is no test suite yet — verification is otherwise empirical: run `just force` (or `just export`) against `assets/example.blend` and inspect the resulting PNGs/JSON.

## Architecture

Two-process pipeline, split because rendering requires Blender's own Python (`bpy`) but the orchestration doesn't:

- **`cmd/export.go`** (backed by `internal/blender`, `internal/manifest`) — the CLI entry point, a plain Go binary with no `bpy` dependency. Finds `.blend` files, checks manifest staleness (`.blend` mtime vs `.json` mtime), and for each stale asset shells out to `blender <asset>.blend --background --python <tmpdir>/blender_scene_export.py -- <out_dir> <px_per_unit> <png_px_per_unit> <pitch_deg>`, where `<tmpdir>` is a fresh directory holding both `blender_scene_export.py` and `shared_materials.blend`, written out from `go:embed`'d copies (Blender's `--python` flag needs a real path on disk, and `go:embed` can't reach outside its own package directory — so `internal/blender/{blender_scene_export.py,shared_materials.blend}` are the only copies of these files; don't recreate copies at the repo root). Both files must land in the *same* temp directory under their original names, since the script locates the materials file via `Path(__file__).parent / "shared_materials.blend"` — splitting them (e.g. reusing `os.CreateTemp` for just the script) silently breaks normal-map rendering with no error, it just finds no `normals` material and skips it. Reads back the JSON that script wrote and reports per-asset stats.
- **`internal/blender/blender_scene_export.py`** — runs *inside* Blender's embedded Python via `--python` (not meant to be run directly; has `import bpy`). Does all the actual scene introspection, camera setup, rendering, and JSON manifest construction for one `.blend` file. Read the module docstring at the top of this file first — it's the authoritative spec for scene conventions and the manifest schema, kept in sync with the code by hand.
- **`internal/blender/shared_materials.blend`** — the fallback library that provides the `normals` material (see below) for any asset that doesn't define its own. `SHARED_MATERIALS_BLEND = Path(__file__).parent / "shared_materials.blend"` in the script is what resolves it, so it always travels alongside the script wherever that gets written out.

Distribution follows the `go-media-manage` pattern: `.goreleaser.yaml` cross-compiles `CGO_ENABLED=0` binaries for darwin/linux × amd64/arm64 on tagged pushes (`.github/workflows/release.yml`), `cmd/update.go` self-updates from the latest GitHub release, and `scripts/install.sh` is the curl-to-install entry point. None of that affects the `blender` runtime dependency — the compiled binary still shells out to whatever `blender` is on `PATH`, same as before.

### Scene conventions (how a `.blend` file should be authored)

- All mesh objects (anything not an Empty/Camera/Light) are combined into one world-space bounding box — that's what auto-framed cameras fit to.
- Four standard 45°-isometric directions are always rendered: NE/NW/SE/SW (compass azimuth in Blender's XY plane, +Y = north). If the scene has a Camera object named after one of those (case-insensitive), its own transform/lens/resolution is used as-is; otherwise one is auto-created and orthographically fit to the bounding box.
- Any other Camera object in the scene is rendered too, as an extra view keyed by its own object name (e.g. a `hero_inventory` camera for an item's inventory-icon shot, distinct from its in-world/equipped views).
- Every Empty in the scene is a named anchor point (e.g. `head`, `weapon_socket`). All camera/direction and Empty names are lowercased (`sanitize_name()`) before becoming manifest keys.
- Every view is rendered a second time with `ViewLayer.material_override` set to a Material named `normals` (case-insensitive) — the asset's own if it has one, else one auto-linked from `shared_materials.blend` — producing a `*_normal.png` per view; the render forces `view_settings.view_transform = "Raw"` so AgX/Filmic doesn't distort the encoded values. That material's shader graph (Geometry Normal → Vector Transform World→Camera → multiply by `(1,1,-1)` to undo a Z-negation quirk in Blender's Vector Transform node → encode to `[0,1]` → Emission) bakes each view's surface normal into its own screen space. No `normals` material anywhere means no normal maps.
- With 2+ Collections directly under the scene's root collection, each is rendered as its own independent asset (`render_asset()` in `blender_scene_export.py`), scoped to just that collection's own objects (`Collection.all_objects`, so nested sub-collections count too) — its own bounding box, cameras, anchors, and normal maps, with every *other* top-level collection's `hide_render` forced on during that asset's renders so they can't bleed into each other's frame. Filenames get the collection name spliced in: `<stem>_<collection>_<view>.png`. With 0 or 1 top-level collections this doesn't kick in at all — the whole scene is one asset, same as always.
- Any object with its own `Object.is_holdout` flag checked (Object Properties → Visibility → Holdout, authored directly in Blender) anywhere in an asset's own objects opts that asset into an automatic front/back split, entirely self-contained per asset (each top-level collection — or the whole scene, with 0/1 of them — is scanned for its own flagged objects independently; no cross-collection reference or shared camera). `render_asset()` scans its own `objects` for `obj.is_holdout` up front and passes all matches to `render_views()`'s `base_objects=` param. `image` keeps its ordinary meaning and is always produced: a render with the holdout object(s) hidden (`hide_render`) entirely, i.e. the complete, unoccluded view of everything else. `split_front_back()` additionally renders the same view with the holdout object(s) visible but `Object.is_holdout` toggled True (Blender's own per-pixel Z-test turned into an alpha cutout), and diffs its alpha against `image`'s — if any pixel is actually cut, that second render is kept and exposed as `overlay_image`; otherwise it's deleted and the key is omitted (`render_views()`'s `overlay_needed` check). Layering `overlay_image` directly onto the same complete `image` (rather than computing two complementary alpha masks that must together sum to full coverage, which the tool did previously) avoids a faint double-transparency seam along the cutout's antialiased edge — `image` already carries full alpha wherever it's genuinely opaque, so any fractional-alpha overlay of the same underlying color composited on top can't push coverage below 1 there. The holdout object(s) still count toward the asset's own bounding box like any other mesh, so they still shape the camera frame, but are never themselves rendered as color. The normal-map pass mirrors `image`: it fully hides the holdout object(s) (`hide_render`, not the holdout flag) so `normal_image` also covers the rest-of-asset geometry's full, unoccluded surface — there's no separate overlay normal map.

### Manifest shape

Single JSON manifest per **file**, not per asset: `{schema_version, ...}`. Two shapes depending on collection count (see above):

```
schema_version 1 (0 or 1 top-level collections): { schema_version, asset, views }
schema_version 2 (2+ top-level collections):     { schema_version, assets: { <collection>: { asset, views }, ... } }
```

`views` is keyed by direction label or camera name — there's no separate top-level table for directions vs. extra cameras vs. anchors; anchors live *nested inside* each view:

```
views.<key> = { image, overlay_image?, normal_image?, render_width_px, render_height_px, anchors }
views.<key>.anchors.<name> = { offset: [-0.5..0.5, -0.5..0.5], visible: bool }
```

The key design point: an anchor's `offset` and `visible` are computed **per view**, not once globally — the same world-space Empty projects to a different screen position in each camera's own frame (this matters especially for custom/extra cameras, which may not share the standard directions' projection convention at all). `offset` is normalized so a consuming engine multiplies it directly by that view's own rendered sprite size to get a pixel offset from the sprite's center. `visible` comes from a scene ray-cast (`anchor_visible()`) so a 2D engine can decide whether to draw an anchor's overlay behind or in front of the sprite.

See the README's "JSON manifest schema" section for full worked examples of both schema versions, and "Scene conventions" for the camera-matching, resolution, and multi-collection rules in prose.
