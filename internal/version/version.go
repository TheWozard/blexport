// Package version holds build-time version metadata injected via -ldflags.
package version

var (
	Version = "dev"
	Commit  = "none"
	Date    = "unknown"
)
