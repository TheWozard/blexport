// Package manifest reads the JSON manifests written by
// blender_scene_export.py and answers the staleness check that decides
// whether a .blend needs re-rendering.
package manifest

import "os"

type Anchor struct {
	Offset  [2]float64 `json:"offset"`
	Visible bool       `json:"visible"`
}

type View struct {
	Image          string            `json:"image"`
	OverlayImage   string            `json:"overlay_image,omitempty"`
	NormalImage    string            `json:"normal_image,omitempty"`
	RenderWidthPx  int               `json:"render_width_px"`
	RenderHeightPx int               `json:"render_height_px"`
	Anchors        map[string]Anchor `json:"anchors"`
}

type AssetInfo struct {
	Name      string     `json:"name"`
	Source    string     `json:"source"`
	PxPerUnit float64    `json:"px_per_unit"`
	BBoxSize  [3]float64 `json:"bbox_size"`
}

type Asset struct {
	Asset AssetInfo       `json:"asset"`
	Views map[string]View `json:"views"`
}

// Manifest covers both schema shapes: schema_version 1 (0/1 top-level
// collections) has Asset/Views directly; schema_version 2 (2+ collections)
// nests per-collection assets under Assets.
type Manifest struct {
	SchemaVersion int              `json:"schema_version"`
	Asset         AssetInfo        `json:"asset,omitempty"`
	Views         map[string]View  `json:"views,omitempty"`
	Assets        map[string]Asset `json:"assets,omitempty"`
}

// AllAssets normalizes both schema shapes into one name->Asset map, using
// the manifest's own top-level asset name as the key under schema 1.
func (m *Manifest) AllAssets() map[string]Asset {
	if m.Assets != nil {
		return m.Assets
	}
	return map[string]Asset{m.Asset.Name: {Asset: m.Asset, Views: m.Views}}
}

// Stale reports whether blendPath is newer than the manifest at
// manifestPath, or the manifest doesn't exist yet.
func Stale(blendPath, manifestPath string) (bool, error) {
	manifestInfo, err := os.Stat(manifestPath)
	if os.IsNotExist(err) {
		return true, nil
	}
	if err != nil {
		return false, err
	}
	blendInfo, err := os.Stat(blendPath)
	if err != nil {
		return false, err
	}
	return blendInfo.ModTime().After(manifestInfo.ModTime()), nil
}
