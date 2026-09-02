// Package blender shells out to a headless Blender to run the embedded
// blender_scene_export.py against one .blend file.
package blender

import (
	"bytes"
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

//go:embed blender_scene_export.py
var sceneExportScript []byte

const sceneExportScriptName = "blender_scene_export.py"

// Run invokes blender in the background against blendPath, running the
// embedded scene-export script with the standard [out_dir, px_per_unit,
// png_px_per_unit, pitch_deg] argv convention. The script itself writes
// <outDir>/<blend-stem>.json plus the rendered PNGs; Run only reports
// whether the blender process itself succeeded.
func Run(blendPath, outDir string, pxPerUnit, pngPxPerUnit, pitchDeg float64) error {
	scriptPath, cleanup, err := writeScriptDir()
	if err != nil {
		return err
	}
	defer cleanup()

	cmd := exec.Command("blender", blendPath,
		"--background", "--python", scriptPath,
		"--", outDir,
		fmt.Sprint(pxPerUnit), fmt.Sprint(pngPxPerUnit), fmt.Sprint(pitchDeg))

	var stderr bytes.Buffer
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("blender failed: %w\n%s", err, stderr.String())
	}
	return nil
}

// writeScriptDir materializes the embedded script into a fresh temp
// directory, since blender's --python flag needs a real path on disk. Each
// call gets its own directory so concurrent Run calls don't collide.
func writeScriptDir() (scriptPath string, cleanup func(), err error) {
	dir, err := os.MkdirTemp("", "blexport-*")
	if err != nil {
		return "", nil, fmt.Errorf("writing embedded script: %w", err)
	}
	cleanup = func() { os.RemoveAll(dir) }

	scriptPath = filepath.Join(dir, sceneExportScriptName)
	if err := os.WriteFile(scriptPath, sceneExportScript, 0644); err != nil {
		cleanup()
		return "", nil, fmt.Errorf("writing embedded script: %w", err)
	}

	return scriptPath, cleanup, nil
}
