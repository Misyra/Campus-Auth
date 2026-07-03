// Campus-Auth 仓库克隆/更新工具
// 自动检测/安装 Git，尝试多个镜像源，支持分支选择
package main

import (
	"bufio"
	"compress/gzip"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ====== 配置 ======

const (
	remoteTimeout = 5 * time.Second
)

// 可直接 git clone 的镜像源（URL 前缀拼接仓库路径）
var mirrors = []struct {
	Name string
	URL  string
}{
	{"GitClone (国内加速)", "https://gitclone.com/github.com/Misyra/Campus-Auth"},
	{"CNPMJS (阿里CDN)", "https://github.com.cnpmjs.org/Misyra/Campus-Auth"},
	{"GHProxy (代理)", "https://mirror.ghproxy.com/https://github.com/Misyra/Campus-Auth"},
	{"GitHub 官方", "https://github.com/Misyra/Campus-Auth"},
}

// ====== 输入工具 ======

// 输入带默认值，回车采用默认
func askInput(prompt, defaultVal string) string {
	fmt.Printf("%s [%s]: ", prompt, defaultVal)
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		input := strings.TrimSpace(scanner.Text())
		if input == "" {
			return defaultVal
		}
		return input
	}
	return defaultVal
}

// 确认操作（y 默认）
func confirm(prompt string) bool {
	fmt.Printf("%s [Y/n]: ", prompt)
	scanner := bufio.NewScanner(os.Stdin)
	if scanner.Scan() {
		return strings.TrimSpace(strings.ToLower(scanner.Text())) != "n"
	}
	return true
}

// ====== Git 检测与安装 ======

// 检测 PATH 中是否有 git
func findGitInPath() string {
	path, err := exec.LookPath("git")
	if err != nil {
		return ""
	}
	return path
}

// 从 environment/ 目录找 git
func findGitInEnv(envDir string) string {
	if runtime.GOOS == "windows" {
		candidates := []string{
			filepath.Join(envDir, "git.exe"),
			filepath.Join(envDir, "Git", "bin", "git.exe"),
			filepath.Join(envDir, "Git", "cmd", "git.exe"),
			filepath.Join(envDir, "mingw64", "bin", "git.exe"),
			filepath.Join(envDir, "mingw32", "bin", "git.exe"),
			filepath.Join(envDir, "bin", "git.exe"),
			filepath.Join(envDir, "cmd", "git.exe"),
		}
		for _, c := range candidates {
			if _, err := os.Stat(c); err == nil {
				return c
			}
		}
	}
	return ""
}

// 确保 git 可用，返回 git 可执行文件路径
func ensureGit(envDir string) string {
	if p := findGitInPath(); p != "" {
		return p
	}
	fmt.Println("  PATH 中未找到 Git，尝试下载...")
	if p := findGitInEnv(envDir); p != "" {
		return p
	}
	if err := downloadGit(envDir); err != nil {
		fmt.Fprintf(os.Stderr, "Git 下载失败: %v\n", err)
		os.Exit(1)
	}
	if p := findGitInEnv(envDir); p != "" {
		return p
	}
	fmt.Fprintln(os.Stderr, "Git 安装后仍无法找到可执行文件")
	os.Exit(1)
	return ""
}

// ====== Git 下载 ======

// 下载 Git 便携版（仅 Windows）
func downloadGit(envDir string) error {
	if runtime.GOOS != "windows" {
		return fmt.Errorf("非 Windows 系统请手动安装 Git: sudo apt install git / brew install git")
	}
	if err := os.MkdirAll(envDir, 0o755); err != nil {
		return err
	}

	downloadURL := "https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/"
	var fileName string

	// 从镜像页获取版本号
	resp, err := http.Get(downloadURL)
	if err == nil {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		html := string(body)
		for _, line := range strings.Split(html, "\n") {
			if strings.Contains(line, "PortableGit-64-bit") && strings.Contains(line, ".7z.exe") {
				start := strings.Index(line, "\"PortableGit")
				if start >= 0 {
					end := strings.Index(line[start+1:], "\"")
					if end > 0 {
						fileName = line[start+1 : start+1+end]
					}
				}
				break
			}
		}
	}

	if fileName == "" {
		fileName = "PortableGit-64-bit-2.47.1.2-64-bit.7z.exe"
	}

	url := downloadURL + fileName
	dest := filepath.Join(envDir, fileName)

	if _, err := os.Stat(dest); err == nil {
		fmt.Println("  已有安装包，跳过下载")
	} else {
		fmt.Printf("  下载: %s\n", url)
		if err := downloadFile(url, dest); err != nil {
			return fmt.Errorf("下载失败: %w", err)
		}
	}

	fmt.Println("  解压中（首次较慢）...")
	cmd := exec.Command(dest, "-o"+envDir, "-y")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
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

// ====== 7z 解压 ======

// 从 gzip 归档解压
func extractGzip(src, destDir string) error {
	f, err := os.Open(src)
	if err != nil {
		return err
	}
	defer f.Close()

	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()

	return extractTar(gz, destDir)
}

// 解压 tar 流
func extractTar(r io.Reader, destDir string) error {
	buf := make([]byte, 32*1024)
	for {
		header := make([]byte, 512)
		if _, err := io.ReadFull(r, header); err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				return nil
			}
			return err
		}

		name := strings.TrimRight(string(header[0:100]), "\x00")
		if name == "" {
			return nil
		}

		sizeStr := strings.TrimRight(string(header[124:136]), "\x00")
		size, _ := strconv.ParseInt(sizeStr, 8, 64)
		if size < 0 {
			return nil
		}

		typeFlag := header[156]
		target := filepath.Join(destDir, name)

		switch typeFlag {
		case '5': // 目录
			os.MkdirAll(target, 0o755)
		case '0', '\x00': // 文件
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
			if err != nil {
				return err
			}
			if _, err := io.CopyBuffer(f, io.LimitReader(r, size), buf); err != nil {
				f.Close()
				return err
			}
			f.Close()
			// 跳过对齐填充
			if pad := size % 512; pad != 0 {
				io.ReadFull(r, make([]byte, 512-pad))
			}
		case '2': // 符号链接
			linkTarget := strings.TrimRight(string(header[157:257]), "\x00")
			os.MkdirAll(filepath.Dir(target), 0o755)
			os.Remove(target)
			os.Symlink(linkTarget, target)
		default:
			// 跳过未知类型
			if size > 0 {
				paddedSize := ((size + 511) / 512) * 512
				io.CopyBuffer(io.Discard, io.LimitReader(r, paddedSize), buf)
			}
		}
	}
}

// ====== Git 操作 ======

// 运行 git 命令，返回输出
func gitRun(gitPath, dir string, args ...string) (string, error) {
	cmd := exec.Command(gitPath, args...)
	if dir != "" {
		cmd.Dir = dir
	}
	out, err := cmd.CombinedOutput()
	return string(out), err
}

// 测试远程仓库是否可达
func isRemoteReachable(gitPath, url string) bool {
	ctx := make(chan struct{})
	go func() {
		time.Sleep(remoteTimeout)
		close(ctx)
	}()

	cmd := exec.Command(gitPath, "ls-remote", "--exit-code", "-h", url)
	done := make(chan error, 1)
	go func() {
		done <- cmd.Run()
	}()

	select {
	case <-ctx:
		cmd.Process.Kill()
		return false
	case err := <-done:
		return err == nil
	}
}

// 获取所有远程分支
func fetchBranches(gitPath, repoDir string) []string {
	gitRun(gitPath, repoDir, "fetch", "--all", "--prune")

	out, _ := gitRun(gitPath, repoDir, "branch", "-r")
	var branches []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line != "" && !strings.Contains(line, "HEAD") {
			branches = append(branches, line)
		}
	}
	sort.Strings(branches)
	return branches
}

// 提示用户选择分支
func promptBranch(branches []string) string {
	if len(branches) == 0 {
		fmt.Println("  未发现远程分支，使用默认分支")
		return ""
	}

	recommended := ""
	displayBranches := make([]string, 0, len(branches))
	for _, b := range branches {
		name := strings.TrimPrefix(b, "origin/")
		displayBranches = append(displayBranches, name)
		if name == "main" || name == "master" {
			recommended = name
		}
	}

	fmt.Println("\n" + strings.Repeat("=", 60))
	fmt.Println("  发现以下远程分支:")
	fmt.Println(strings.Repeat("-", 60))
	for i, name := range displayBranches {
		marker := "  "
		if name == recommended {
			marker = "★ "
		}
		fmt.Printf("  %s[%d] %s\n", marker, i+1, name)
	}
	fmt.Println(strings.Repeat("-", 60))
	if recommended != "" {
		fmt.Printf("  ★ 推荐使用 [%s] — 主分支，最稳定\n", recommended)
	}
	fmt.Println(strings.Repeat("=", 60))

	for {
		input := askInput("选择分支（输入编号或名称）", recommended)
		if input == "" {
			return recommended
		}

		if idx, err := strconv.Atoi(input); err == nil && idx >= 1 && idx <= len(displayBranches) {
			return displayBranches[idx-1]
		}

		for _, name := range displayBranches {
			if name == input {
				return name
			}
		}

		fmt.Printf("  无效选择，请重新输入（1-%d 或分支名称）\n", len(displayBranches))
	}
}

// 检查目录是否为 git 仓库
func isGitDir(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, ".git"))
	return err == nil
}

// 检查目录是否存在
func dirExists(dir string) bool {
	info, err := os.Stat(dir)
	return err == nil && info.IsDir()
}

// 检查文件是否存在
func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// ====== 主逻辑 ======

// 尝试用镜像源 fetch（返回可用的 remote URL）
func tryFetchWithMirrors(gitPath, repoDir string) string {
	for i, m := range mirrors {
		fmt.Printf("\n[%d/%d] 尝试: %s\n", i+1, len(mirrors), m.Name)
		fmt.Printf("  %s\n", m.URL)

		if i < len(mirrors)-1 {
			fmt.Print("  测试连接...")
			if !isRemoteReachable(gitPath, m.URL) {
				fmt.Println("不可达，跳过")
				continue
			}
			fmt.Println("OK")
		}

		// 设置 remote 并 fetch
		gitRun(gitPath, repoDir, "remote", "remove", "origin")
		gitRun(gitPath, repoDir, "remote", "add", "origin", m.URL)

		fmt.Print("  Fetch 中...")
		if _, err := gitRun(gitPath, repoDir, "fetch", "origin", "--depth", "1"); err != nil {
			fmt.Println("失败")
			continue
		}
		fmt.Println("OK")
		return m.URL
	}
	return ""
}

// 目录存在但不是 Git 仓库 → init + remote add + fetch + reset
func doInitAndSync(gitPath, repoDir string) {
	// repoDir 现在是完整路径，目录必定存在（从 main 进入）
	fmt.Printf("\n检测到目录: %s\n", repoDir)
	fmt.Println("⚠ 此操作将重置目录内容为远程仓库最新状态，本地未备份的文件将丢失!")
	if !confirm("是否继续?") {
		fmt.Println("已取消")
		os.Exit(0)
	}

	// git init
	fmt.Println("\n[初始化] git init...")
	if _, err := gitRun(gitPath, repoDir, "init"); err != nil {
		fmt.Fprintf(os.Stderr, "git init 失败: %v\n", err)
		os.Exit(1)
	}

	// 尝试镜像 fetch（成功后 origin 已设置，远程分支已拉取）
	fmt.Println("[连接] 尝试镜像源...")
	if tryFetchWithMirrors(gitPath, repoDir) == "" {
		fmt.Fprintln(os.Stderr, "\n所有镜像均失败，请检查网络")
		os.Exit(1)
	}

	// 直接列出已 fetch 的远程分支（不需要再次 fetch）
	out, _ := gitRun(gitPath, repoDir, "branch", "-r")
	var branches []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line != "" && !strings.Contains(line, "HEAD") {
			branches = append(branches, line)
		}
	}
	sort.Strings(branches)

	branch := promptBranch(branches)
	if branch == "" {
		branch = "main"
	}

	// reset --hard 到远程分支
	fmt.Printf("\n[同步] 重置到 origin/%s...\n", branch)
	if _, err := gitRun(gitPath, repoDir, "reset", "--hard", "origin/"+branch); err != nil {
		fmt.Fprintf(os.Stderr, "重置失败: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("\n✓ 同步完成! 分支: %s\n", branch)
}

func doUpdate(gitPath, repoDir string) {
	// repoDir 现在是完整路径
	if _, err := os.Stat(repoDir); os.IsNotExist(err) {
		fmt.Fprintf(os.Stderr, "目录不存在: %s\n", repoDir)
		os.Exit(1)
	}
	if !isGitDir(repoDir) {
		fmt.Fprintf(os.Stderr, "不是 Git 仓库: %s\n", repoDir)
		os.Exit(1)
	}

	// 获取当前分支
	out, _ := gitRun(gitPath, repoDir, "branch", "--show-current")
	branch := strings.TrimSpace(out)
	if branch == "" {
		branch = "main"
	}

	// 检查是否有未提交修改
	status, _ := gitRun(gitPath, repoDir, "status", "--porcelain")
	if strings.TrimSpace(status) != "" {
		fmt.Println("\n⚠ 仓库有未提交的修改，重置将丢失所有本地更改!")
		if !confirm("是否继续更新（将重置为远程最新状态）?") {
			fmt.Println("已取消")
			os.Exit(0)
		}
	}

	fmt.Printf("\n更新仓库: %s\n", repoDir)

	// fetch + reset 到远程最新
	gitRun(gitPath, repoDir, "fetch", "origin", branch)
	if _, err := gitRun(gitPath, repoDir, "reset", "--hard", "origin/"+branch); err != nil {
		fmt.Printf("  更新失败: %v\n", err)
		os.Exit(1)
	}

	// 重新获取所有分支
	branches := fetchBranches(gitPath, repoDir)
	newBranch := promptBranch(branches)

	if newBranch != "" && newBranch != branch {
		if _, err := gitRun(gitPath, repoDir, "checkout", newBranch); err != nil {
			gitRun(gitPath, repoDir, "checkout", "-b", newBranch, "origin/"+newBranch)
		}
		gitRun(gitPath, repoDir, "pull", "origin", newBranch)
	}

	// 最终更新
	gitRun(gitPath, repoDir, "pull", "origin", branch)

	fmt.Println("\n✓ 更新完成!")
}

// ====== 入口 ======

func main() {
	// Windows 控制台 UTF-8
	if runtime.GOOS == "windows" {
		exec.Command("chcp.com", "65001").Run()
	}

	fmt.Println(`============================================
  Campus-Auth 仓库克隆/更新工具
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

	// Step 1: 确保 Git 可用
	fmt.Println("\n[1/3] 检测 Git 环境...")
	envDir := "environment"
	gitPath := ensureGit(envDir)
	fmt.Printf("  Git: %s\n", gitPath)

	// Step 2: 根据当前目录状态选择模式
	if isGitDir(wd) {
		// 已有 Git 仓库 → 更新
		fmt.Println("\n[2/3] 检测到已有仓库，进入更新模式...")
		doUpdate(gitPath, wd)
	} else {
		// 目录存在但不是 Git 仓库 → 初始化并同步
		fmt.Println("\n[2/3] 非 Git 仓库，进入初始化模式...")
		doInitAndSync(gitPath, wd)
	}

	// Step 3: 完成
	fmt.Println("\n" + strings.Repeat("=", 60))
	fmt.Println("  ✓ 操作完成!")
	fmt.Printf("  目录: %s\n", wd)
	fmt.Println(strings.Repeat("=", 60))
}
