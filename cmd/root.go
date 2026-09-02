// Package cmd implements the CLI commands for blexport.
package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/TheWozard/blexport/internal/version"
)

var rootCmd = &cobra.Command{
	Use:     "blexport",
	Short:   "Render .blend game assets into per-direction PNGs and JSON manifests",
	Version: version.Version,
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
