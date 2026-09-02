package cmd

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"image"
	_ "image/png"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/TheWozard/blexport/internal/blender"
	"github.com/TheWozard/blexport/internal/manifest"
)

var updateGolden = flag.Bool("update", false, "print an updated goldenManifestChecksums block instead of comparing against it")

const (
	testPxPerUnit   = 32.0
	testSupersample = 4.0
	testPitch       = 35.264
)

// goldenManifestChecksums is "<manifest filename> <sha256>" per line, one
// per .blend under assets/. Regenerate with:
//
//	go test ./cmd/... -run TestExportAssetsSnapshot -update -v
//
// and paste the logged block back in here.
const goldenManifestChecksums = `
example.json c4f59ea962693698c96db8c2dc567a51d1d1932e70aa4a5e11b4c2a0af7d8dde
`

// TestExportAssetsSnapshot renders every .blend under the repo's assets/
// directory and checks each resulting JSON manifest against a golden sha256
// checksum, plus structurally validates every PNG the manifest references
// (exists, decodes, and matches the manifest's own declared dimensions).
//
// Raw PNG bytes are deliberately not checksummed: two back-to-back renders
// of the same unmodified scene produce byte-different PNGs every time
// (confirmed empirically) — Blender's dithering/sampling isn't
// bit-reproducible run to run, and that's controlled by each .blend's own
// render settings, not by this tool. The JSON manifest, by contrast, was
// confirmed byte-identical across repeated runs of the same code, so it's
// what actually carries a meaningful regression signal here.
func TestExportAssetsSnapshot(t *testing.T) {
	if _, err := exec.LookPath("blender"); err != nil {
		t.Skip("blender not on PATH, skipping export snapshot test")
	}

	assetsDir, err := filepath.Abs(filepath.Join("..", "assets"))
	if err != nil {
		t.Fatal(err)
	}
	blends, err := findBlends(assetsDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(blends) == 0 {
		t.Fatal("no .blend files found under assets/")
	}

	got := map[string]string{}
	for _, blend := range blends {
		outDir := t.TempDir()
		pngPxPerUnit := testPxPerUnit * testSupersample
		if err := blender.Run(blend, outDir, testPxPerUnit, pngPxPerUnit, testPitch); err != nil {
			t.Fatalf("rendering %s: %s", filepath.Base(blend), err)
		}

		stem := strings.TrimSuffix(filepath.Base(blend), filepath.Ext(blend))
		manifestName := stem + ".json"
		data, err := os.ReadFile(filepath.Join(outDir, manifestName))
		if err != nil {
			t.Fatalf("%s: reading manifest: %s", stem, err)
		}

		var m manifest.Manifest
		if err := json.Unmarshal(data, &m); err != nil {
			t.Fatalf("%s: parsing manifest: %s", stem, err)
		}
		validateRenderedViews(t, stem, outDir, m.AllAssets())

		sum := sha256.Sum256(data)
		got[manifestName] = hex.EncodeToString(sum[:])
	}

	if *updateGolden {
		logGolden(t, got)
		return
	}
	compareGolden(t, parseGolden(t, goldenManifestChecksums), got)
}

// validateRenderedViews checks every image/overlay_image/normal_image the
// manifest references actually exists, decodes as a PNG, and matches the
// width/height the manifest itself claims for that view.
func validateRenderedViews(t *testing.T, stem, outDir string, assets map[string]manifest.Asset) {
	t.Helper()
	for assetName, asset := range assets {
		for viewName, view := range asset.Views {
			files := map[string]string{
				"image":         view.Image,
				"overlay_image": view.OverlayImage,
				"normal_image":  view.NormalImage,
			}
			for label, filename := range files {
				if filename == "" {
					continue
				}
				checkRenderedPNG(t, filepath.Join(outDir, filename), view.RenderWidthPx, view.RenderHeightPx,
					fmt.Sprintf("%s/%s/%s (%s)", stem, assetName, viewName, label))
			}
		}
	}
}

func checkRenderedPNG(t *testing.T, path string, wantWidth, wantHeight int, label string) {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Errorf("%s: %s", label, err)
		return
	}
	defer f.Close()

	cfg, _, err := image.DecodeConfig(f)
	if err != nil {
		t.Errorf("%s: decoding PNG: %s", label, err)
		return
	}
	if cfg.Width != wantWidth || cfg.Height != wantHeight {
		t.Errorf("%s: got %dx%d, manifest says %dx%d", label, cfg.Width, cfg.Height, wantWidth, wantHeight)
	}
}

func parseGolden(t *testing.T, block string) map[string]string {
	t.Helper()
	want := map[string]string{}
	for _, line := range strings.Split(strings.TrimSpace(block), "\n") {
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) != 2 {
			t.Fatalf("malformed golden line: %q", line)
		}
		want[fields[0]] = fields[1]
	}
	return want
}

func logGolden(t *testing.T, got map[string]string) {
	t.Helper()
	names := make([]string, 0, len(got))
	for name := range got {
		names = append(names, name)
	}
	sort.Strings(names)

	var b strings.Builder
	b.WriteString("\n")
	for _, name := range names {
		fmt.Fprintf(&b, "%s %s\n", name, got[name])
	}
	t.Logf("paste this into goldenManifestChecksums in export_test.go:\nconst goldenManifestChecksums = `%s`", b.String())
}

func compareGolden(t *testing.T, want, got map[string]string) {
	t.Helper()
	for name, gotSum := range got {
		wantSum, ok := want[name]
		if !ok {
			t.Errorf("%s: no golden entry for this manifest (run with -update to add it)", name)
			continue
		}
		if gotSum != wantSum {
			t.Errorf("%s: manifest checksum changed\n  want %s\n  got  %s\n(if this change is expected, run with -update)", name, wantSum, gotSum)
		}
	}
	for name := range want {
		if _, ok := got[name]; !ok {
			t.Errorf("%s: golden entry exists but this run didn't produce it", name)
		}
	}
}
