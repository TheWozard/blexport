package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/TheWozard/blexport/internal/blender"
	"github.com/TheWozard/blexport/internal/manifest"
)

var (
	exportOut         string
	exportForce       bool
	exportPxPerUnit   float64
	exportSupersample float64
	exportPitch       float64
)

var exportCmd = &cobra.Command{
	Use:   "export <blend-file-or-directory>",
	Short: "Render every stale .blend file under path",
	Args:  cobra.ExactArgs(1),
	RunE:  runExport,
}

func init() {
	exportCmd.Flags().StringVar(&exportOut, "out", "", "output directory (default: alongside each .blend)")
	exportCmd.Flags().BoolVar(&exportForce, "force", false, "re-render even if the manifest is up to date")
	exportCmd.Flags().Float64Var(&exportPxPerUnit, "px-per-unit", 32, "game display pixels per Blender unit")
	exportCmd.Flags().Float64Var(&exportSupersample, "supersample", 4, "rendered PNG pixels per display pixel, for auto-framed cameras")
	exportCmd.Flags().Float64Var(&exportPitch, "pitch", 35.264, "camera pitch below horizontal, in degrees, for auto-framed cameras")
	rootCmd.AddCommand(exportCmd)
}

func runExport(cmd *cobra.Command, args []string) error {
	cmd.SilenceUsage = true

	if _, err := exec.LookPath("blender"); err != nil {
		return fmt.Errorf("blender not found on PATH — install from https://www.blender.org/download/ (or `brew install --cask blender`)")
	}

	blends, err := findBlends(args[0])
	if err != nil {
		return err
	}
	if len(blends) == 0 {
		return fmt.Errorf("no .blend files found under %s", args[0])
	}

	ok := 0
	for _, blend := range blends {
		outDir := exportOut
		if outDir == "" {
			outDir = filepath.Dir(blend)
		}
		if err := os.MkdirAll(outDir, 0755); err != nil {
			return err
		}

		stem := strings.TrimSuffix(filepath.Base(blend), filepath.Ext(blend))
		manifestPath := filepath.Join(outDir, stem+".json")

		if !exportForce {
			isStale, err := manifest.Stale(blend, manifestPath)
			if err != nil {
				return err
			}
			if !isStale {
				fmt.Printf("%s: up to date, skipping\n", filepath.Base(blend))
				ok++
				continue
			}
		}

		if processBlend(blend, outDir, manifestPath) {
			ok++
		}
	}

	fmt.Printf("\n%d/%d asset(s) exported.\n", ok, len(blends))
	if ok < len(blends) {
		os.Exit(1)
	}
	return nil
}

// processBlend renders one .blend and prints a per-asset summary. It
// reports success/failure itself (rather than returning an error) so one
// bad asset doesn't abort the batch, matching export.py's behavior.
func processBlend(blend, outDir, manifestPath string) bool {
	fmt.Printf("%s:\n", filepath.Base(blend))

	pngPxPerUnit := exportPxPerUnit * exportSupersample
	if err := blender.Run(blend, outDir, exportPxPerUnit, pngPxPerUnit, exportPitch); err != nil {
		fmt.Fprintf(os.Stderr, "  ✗ %s\n", err)
		return false
	}

	data, err := os.ReadFile(manifestPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "  ✗ blender exited ok but wrote no manifest: %s\n", err)
		return false
	}
	var m manifest.Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		fmt.Fprintf(os.Stderr, "  ✗ parsing manifest: %s\n", err)
		return false
	}

	assets := m.AllAssets()
	fmt.Printf("  wrote %s (%d asset(s)):\n", filepath.Base(manifestPath), len(assets))
	for name, asset := range assets {
		fmt.Printf("    %s: %s\n", name, summarizeViews(asset.Views))
	}
	return true
}

func summarizeViews(views map[string]manifest.View) string {
	compassDirs := map[string]bool{"ne": true, "nw": true, "se": true, "sw": true}
	nDirs, nAnchors := 0, 0
	for key, v := range views {
		if compassDirs[strings.ToLower(key)] {
			nDirs++
		}
		if nAnchors == 0 {
			nAnchors = len(v.Anchors)
		}
	}
	return fmt.Sprintf("%d direction(s), %d extra camera(s), %d anchor(s)", nDirs, len(views)-nDirs, nAnchors)
}

// findBlends returns path itself if it's a .blend file, or every .blend
// found recursively under it if it's a directory, sorted for stable output.
func findBlends(path string) ([]string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("accessing %s: %w", path, err)
	}
	if !info.IsDir() {
		return []string{path}, nil
	}

	var blends []string
	err = filepath.WalkDir(path, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && strings.EqualFold(filepath.Ext(p), ".blend") {
			blends = append(blends, p)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(blends)
	return blends, nil
}
