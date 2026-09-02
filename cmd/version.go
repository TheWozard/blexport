package cmd

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/TheWozard/blexport/internal/version"
)

var versionCmd = &cobra.Command{
	Use:   "version",
	Short: "Print the blexport version",
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Printf("blexport %s (%s, built %s)\n", version.Version, version.Commit, version.Date)
	},
}

func init() {
	rootCmd.AddCommand(versionCmd)
}
