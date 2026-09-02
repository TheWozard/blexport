package cmd

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/spf13/cobra"

	"github.com/TheWozard/blexport/internal/version"
)

const (
	githubOwner = "TheWozard"
	githubRepo  = "blexport"
	binaryName  = "blexport"
)

type githubAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

type githubRelease struct {
	TagName string        `json:"tag_name"`
	Assets  []githubAsset `json:"assets"`
}

var updateCheckOnly bool

var updateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update blexport to the latest released version",
	RunE: func(cmd *cobra.Command, args []string) error {
		cmd.SilenceUsage = true
		return runUpdate(updateCheckOnly)
	},
}

func init() {
	updateCmd.Flags().BoolVar(&updateCheckOnly, "check", false, "check for a new version without installing it")
	rootCmd.AddCommand(updateCmd)
}

func runUpdate(checkOnly bool) error {
	release, err := fetchLatestRelease()
	if err != nil {
		return fmt.Errorf("checking latest release: %w", err)
	}

	current := strings.TrimPrefix(version.Version, "v")
	latest := strings.TrimPrefix(release.TagName, "v")

	if current == latest {
		fmt.Printf("Already up to date (%s).\n", release.TagName)
		return nil
	}

	fmt.Printf("Current version: %s\n", version.Version)
	fmt.Printf("Latest version:  %s\n", release.TagName)

	if checkOnly {
		fmt.Println("Run `blexport update` to install the latest version.")
		return nil
	}

	assetName := fmt.Sprintf("%s_%s_%s.tar.gz", binaryName, runtime.GOOS, runtime.GOARCH)
	asset := findAsset(release.Assets, assetName)
	if asset == nil {
		return fmt.Errorf("no release asset found for %s/%s (expected %s)", runtime.GOOS, runtime.GOARCH, assetName)
	}

	archiveData, err := downloadAsset(asset.BrowserDownloadURL)
	if err != nil {
		return fmt.Errorf("downloading %s: %w", asset.Name, err)
	}

	if sums := findAsset(release.Assets, "checksums.txt"); sums != nil {
		if err := verifyChecksum(sums.BrowserDownloadURL, asset.Name, archiveData); err != nil {
			return fmt.Errorf("verifying checksum: %w", err)
		}
	}

	binaryData, err := extractBinary(archiveData, binaryName)
	if err != nil {
		return fmt.Errorf("extracting %s: %w", asset.Name, err)
	}

	if err := replaceRunningBinary(binaryData); err != nil {
		return fmt.Errorf("installing update: %w", err)
	}

	fmt.Printf("Updated to %s.\n", release.TagName)
	return nil
}

func fetchLatestRelease() (*githubRelease, error) {
	url := fmt.Sprintf("https://api.github.com/repos/%s/%s/releases/latest", githubOwner, githubRepo)
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status %s", resp.Status)
	}

	var release githubRelease
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return nil, err
	}
	return &release, nil
}

func findAsset(assets []githubAsset, name string) *githubAsset {
	for i := range assets {
		if assets[i].Name == name {
			return &assets[i]
		}
	}
	return nil
}

func downloadAsset(url string) ([]byte, error) {
	resp, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status %s", resp.Status)
	}
	return io.ReadAll(resp.Body)
}

func verifyChecksum(checksumsURL, assetName string, data []byte) error {
	body, err := downloadAsset(checksumsURL)
	if err != nil {
		return err
	}

	sum := sha256.Sum256(data)
	want := hex.EncodeToString(sum[:])

	for _, line := range strings.Split(string(body), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[1] == assetName {
			if fields[0] != want {
				return fmt.Errorf("checksum mismatch: got %s, want %s", want, fields[0])
			}
			return nil
		}
	}
	return fmt.Errorf("no checksum entry for %s", assetName)
}

func extractBinary(archiveData []byte, name string) ([]byte, error) {
	gz, err := gzip.NewReader(bytes.NewReader(archiveData))
	if err != nil {
		return nil, err
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if hdr.Typeflag != tar.TypeReg {
			continue
		}
		if filepath.Base(hdr.Name) == name {
			return io.ReadAll(tr)
		}
	}
	return nil, fmt.Errorf("binary %q not found in archive", name)
}

func replaceRunningBinary(data []byte) error {
	execPath, err := os.Executable()
	if err != nil {
		return err
	}
	execPath, err = filepath.EvalSymlinks(execPath)
	if err != nil {
		return err
	}

	info, err := os.Stat(execPath)
	if err != nil {
		return err
	}

	dir := filepath.Dir(execPath)
	tmp, err := os.CreateTemp(dir, ".blexport-update-*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath) // no-op once renamed into place

	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpPath, info.Mode()); err != nil {
		return err
	}
	return os.Rename(tmpPath, execPath)
}
