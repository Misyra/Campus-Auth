// Campus-Auth 仓库 Release 下载/更新工具
// 自动获取最新 Release，下载 zip 包并替换本地文件
// 保留 environment/ 和 resources/ 目录
package main

import (
	"archive/zip"
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// ====== 配置 ======

const (
	repoOwner = "Misyra"
	repoName  = "Campus-Auth"
)

// Release 下载镜像源（替换域名/路径前缀）
var downloadMirrors = []struct {
	Name   string
	APIURL string // releases API 的镜像
	DLBase string // zip 下载的镜像基址
}{
	{"GitHub 官方", "https://api.github.com", "https://github.com"},
	{"GHProxy (代理)", "https://api.github.com", "https://mirror.ghproxy.com/https://github.com"},
	{"GitClone (国内加速)", "https://api.github.com", "https://gitclone.com/github.com"},
}

// ====== 输入工具 ======

// 输入带默认值，回车采用默认
func askInput(prompt, defaultVal string) string {
	if defaultVal != "" {
		fmt.Printf("  %s [%s]: ", prompt, defaultVal)
	} else {
		fmt.Printf("  %s: ", prompt)
	}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Scan()
	text := strings.TrimSpace(scanner.Text())
	if text == "" {
		return defaultVal
	}
	return text
}

// 确认操作（y 默认）
func confirm(prompt string) bool {
	fmt.Printf("  %s [Y/n] ", prompt)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Scan()
	text := strings.TrimSpace(strings.ToLower(scanner.Text()))
	return text == "" || text == "y" || text == "yes"
}

// ====== 下载工具 ======

type progressWriter struct {
	total   int64
	current int64
	start   time.Time
	done    bool
}

func (pw *progressWriter) Write(p []byte) (int, error) {
	n := len(p)
	pw.current += int64(n)
	pw.print()
	return n, nil
}

func (pw *progressWriter) print() {
	if pw.done {
		return
	}
	elapsed := time.Since(pw.start).Seconds()
	speed := float64(pw.current) / 1024 / 1024 / elapsed
	if speed < 0.01 {
		speed = 0
	}

	var pct float64
	if pw.total > 0 {
		pct = float64(pw.current) / float64(pw.total) * 100
	}

	fmt.Printf("\r  [%-50s] %5.1f%%  %.1f MB/s",
		strings.Repeat("█", int(pct/2)),
		pct, speed)

	if pw.current >= pw.total && pw.total > 0 {
		pw.done = true
		fmt.Println()
	}
}

func downloadFile(url, dest string) error {
	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()

	pw := &progressWriter{total: resp.ContentLength, start: time.Now()}
	if pw.total == 0 {
		pw.total = 1 << 30
	}

	_, err = io.Copy(f, io.TeeReader(resp.Body, pw))
	if err != nil {
		return err
	}

	if !pw.done {
		pw.done = true
		fmt.Println()
	}
	return nil
}

// ====== Release API ======

// GitHub Release 资产信息
type releaseAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
	Size               int64  `json:"size"`
}

// GitHub Release 信息
type releaseInfo struct {
	TagName string         `json:"tag_name"`
	Name    string         `json:"name"`
	Assets  []releaseAsset `json:"assets"`
	ZipURL  string         `json:"zipball_url"`
}

// 从 GitHub API 获取最新 Release 信息
func fetchLatestRelease(apiBase string) (*releaseInfo, error) {
	url := fmt.Sprintf("%s/repos/%s/%s/releases/latest", apiBase, repoOwner, repoName)
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	var info releaseInfo
	if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
		return nil, err
	}
	return &info, nil
}

// 从多个 Release 中让用户选择
func fetchReleases(apiBase string, limit int) ([]releaseInfo, error) {
	url := fmt.Sprintf("%s/repos/%s/%s/releases?per_page=%d", apiBase, repoOwner, repoName, limit)
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	var releases []releaseInfo
	if err := json.NewDecoder(resp.Body).Decode(&releases); err != nil {
		return nil, err
	}
	return releases, nil
}

// 提示用户选择 Release
func promptRelease(releases []releaseInfo) releaseInfo {
	if len(releases) == 0 {
		fmt.Println("  无可用 Release")
		os.Exit(1)
	}
	if len(releases) == 1 {
		return releases[0]
	}

	fmt.Println("\n" + strings.Repeat("=", 60))
	fmt.Println("  发现以下 Release:")
	fmt.Println(strings.Repeat("-", 60))
	for i, r := range releases {
		marker := "  "
		if i == 0 {
			marker = "★ "
		}
		name := r.Name
		if name == "" {
			name = r.TagName
		}
		fmt.Printf("  %s[%d] %s (%s)\n", marker, i+1, name, r.TagName)
	}
	fmt.Println(strings.Repeat("-", 60))
	fmt.Println("  ★ 推荐使用最新版本")
	fmt.Println(strings.Repeat("=", 60))

	for {
		input := askInput("选择版本（输入编号）", "1")
		if idx, err := strconv.Atoi(input); err == nil && idx >= 1 && idx <= len(releases) {
			return releases[idx-1]
		}
		fmt.Printf("  无效选择，请重新输入（1-%d）\n", len(releases))
	}
}

// 选择下载 URL：优先用源码 zip，没有则用第一个 asset
func selectDownloadURL(release releaseInfo, dlBase string) string {
	// 优先用 zipball_url（源码包），替换域名
	if release.ZipURL != "" {
		// 将 github.com 替换为镜像地址
		url := release.ZipURL
		url = strings.Replace(url, "https://github.com", dlBase, 1)
		return url
	}

	// 没有 zipball_url，用 assets 中的 zip
	for _, a := range release.Assets {
		if strings.HasSuffix(a.Name, ".zip") {
			url := a.BrowserDownloadURL
			url = strings.Replace(url, "https://github.com", dlBase, 1)
			return url
		}
	}

	return ""
}

// ====== ZIP 解压 ======

// 解压 zip 文件到目标目录，返回解压后的根目录名（如 Campus-Auth-xxx）
func extractZip(zipPath, destDir string) (string, error) {
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		return "", err
	}
	defer r.Close()

	rootPrefix := ""

	for _, f := range r.File {
		// 获取 zip 内第一级目录名（GitHub 源码包格式: owner-repo-hash/...）
		parts := strings.SplitN(f.Name, "/", 2)
		if rootPrefix == "" && len(parts) > 1 {
			rootPrefix = parts[0]
		}

		// 路径穿越检查
		target := filepath.Join(destDir, f.Name)
		if !strings.HasPrefix(filepath.Clean(target), filepath.Clean(destDir)+string(os.PathSeparator)) &&
			filepath.Clean(target) != filepath.Clean(destDir) {
			continue
		}

		if f.FileInfo().IsDir() {
			os.MkdirAll(target, 0o755)
			continue
		}

		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return rootPrefix, err
		}

		outFile, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, f.Mode())
		if err != nil {
			return rootPrefix, err
		}

		rc, err := f.Open()
		if err != nil {
			outFile.Close()
			return rootPrefix, err
		}

		_, err = io.Copy(outFile, rc)
		rc.Close()
		outFile.Close()
		if err != nil {
			return rootPrefix, err
		}
	}

	return rootPrefix, nil
}

// ====== 文件操作 ======

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// 递归复制目录
func copyDir(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		relPath, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, relPath)
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode())
		}
		return copyFile(path, target)
	})
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}

// ====== 主逻辑 ======

func doUpdate(repoDir string) {
	// 1. 获取最新 Release
	fmt.Println("\n[1/3] 获取 Release 信息...")

	var release *releaseInfo
	var usedMirror string
	for _, m := range downloadMirrors {
		fmt.Printf("  尝试: %s...", m.Name)
		r, err := fetchLatestRelease(m.APIURL)
		if err != nil {
			fmt.Printf(" 失败 (%v)\n", err)
			continue
		}
		fmt.Println(" OK")
		release = r
		usedMirror = m.Name
		break
	}

	if release == nil {
		fmt.Fprintln(os.Stderr, "\n无法获取 Release 信息，请检查网络连接")
		os.Exit(1)
	}

	relName := release.Name
	if relName == "" {
		relName = release.TagName
	}
	fmt.Printf("  最新版本: %s (%s) [via %s]\n", relName, release.TagName, usedMirror)

	// 2. 下载 zip 包
	fmt.Println("\n[2/3] 下载 Release 包...")

	var mirror = downloadMirrors[0] // 找到可用的镜像
	for _, m := range downloadMirrors {
		if m.Name == usedMirror {
			mirror = m
			break
		}
	}

	dlURL := selectDownloadURL(*release, mirror.DLBase)
	if dlURL == "" {
		fmt.Fprintln(os.Stderr, "找不到可下载的 zip 包")
		os.Exit(1)
	}

	tmpDir := filepath.Join(os.TempDir(), "campus-auth-update")
	os.MkdirAll(tmpDir, 0o755)
	zipPath := filepath.Join(tmpDir, release.TagName+".zip")

	fmt.Printf("  URL: %s\n", dlURL)
	if err := downloadFile(dlURL, zipPath); err != nil {
		fmt.Fprintf(os.Stderr, "\n下载失败: %v\n", err)
		os.Exit(1)
	}

	// 3. 解压到临时目录，确认成功后覆盖
	fmt.Println("\n[3/3] 解压并替换文件...")

	extractDir := filepath.Join(tmpDir, "extracted")
	os.MkdirAll(extractDir, 0o755)

	rootPrefix, err := extractZip(zipPath, extractDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "解压失败: %v\n", err)
		os.Exit(1)
	}

	// 解压后的源码目录
	srcDir := extractDir
	if rootPrefix != "" {
		srcDir = filepath.Join(extractDir, rootPrefix)
	}

	// 覆盖到项目目录
	fmt.Println("  覆盖文件...")
	newEntries, err := os.ReadDir(srcDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "读取解压目录失败: %v\n", err)
		os.Exit(1)
	}
	for _, entry := range newEntries {
		src := filepath.Join(srcDir, entry.Name())
		dst := filepath.Join(repoDir, entry.Name())
		if entry.IsDir() {
			if err := copyDir(src, dst); err != nil {
				fmt.Fprintf(os.Stderr, "  复制 %s 失败: %v\n", entry.Name(), err)
				os.Exit(1)
			}
		} else {
			if err := copyFile(src, dst); err != nil {
				fmt.Fprintf(os.Stderr, "  复制 %s 失败: %v\n", entry.Name(), err)
				os.Exit(1)
			}
		}
	}

	// 清理临时目录
	os.RemoveAll(tmpDir)

	// 完成
	fmt.Printf("\n✓ 更新完成! 版本: %s\n", relName)
}

func doListReleases(repoDir string) {
	fmt.Println("\n获取 Release 列表...")

	var releases []releaseInfo
	for _, m := range downloadMirrors {
		fmt.Printf("  尝试: %s...", m.Name)
		rls, err := fetchReleases(m.APIURL, 10)
		if err != nil {
			fmt.Printf(" 失败 (%v)\n", err)
			continue
		}
		fmt.Println(" OK")
		releases = rls
		break
	}

	if len(releases) == 0 {
		fmt.Fprintln(os.Stderr, "无法获取 Release 列表")
		os.Exit(1)
	}

	_ = promptRelease(releases) // 显示列表供用户参考
}

// ====== 入口 ======

func main() {
	// Windows 控制台 UTF-8
	if runtime.GOOS == "windows" {
		os.Setenv("PYTHONIOENCODING", "utf-8")
	}

	fmt.Println(`============================================
  Campus-Auth Release 下载/更新工具
============================================`)

	// 校验：必须在 Campus-Auth 项目目录下运行
	wd, _ := os.Getwd()
	if !fileExists(filepath.Join(wd, "pyproject.toml")) {
		fmt.Println("错误: 请将此程序放在 Campus-Auth 项目根目录下运行")
		fmt.Println("      （需要与 pyproject.toml 同一目录）")
		fmt.Print("\n按回车键退出...")
		bufio.NewScanner(os.Stdin).Scan()
		os.Exit(1)
	}

	// 根据参数选择模式
	if len(os.Args) > 1 && os.Args[1] == "list" {
		doListReleases(wd)
		return
	}

	// 检测当前版本
	fmt.Println("\n[检测] 当前环境...")
	versionFile := filepath.Join(wd, "pyproject.toml")
	if fileExists(versionFile) {
		data, err := os.ReadFile(versionFile)
		if err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				if strings.HasPrefix(line, "version") {
					fmt.Printf("  当前版本: %s\n", strings.TrimSpace(strings.TrimPrefix(line, "version")))
					break
				}
			}
		}
	}

	// 确认更新
	fmt.Println()
	if !confirm("是否检查并更新到最新 Release?") {
		fmt.Println("已取消")
		return
	}

	doUpdate(wd)

	fmt.Println("\n" + strings.Repeat("=", 60))
	fmt.Println("  ✓ 操作完成!")
	fmt.Printf("  目录: %s\n", wd)
	fmt.Println(strings.Repeat("=", 60))
	fmt.Print("\n按回车键退出...")
	bufio.NewScanner(os.Stdin).Scan()
}
