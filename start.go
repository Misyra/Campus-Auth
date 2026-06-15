// Campus-Auth 启动程序
// 自动下载 uv、安装依赖、启动应用
// 用法: start.exe [--install-only] [其他参数透传给 main.py]
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

const (
	uvVersion = "0.7.3"
)

// getUvFilename 根据系统架构返回对应的 uv 文件名
func getUvFilename() string {
	if runtime.GOARCH == "arm64" {
		return "uv-aarch64-pc-windows-msvc.zip"
	}
	return "uv-x86_64-pc-windows-msvc.zip"
}

var mirrors = []string{
	"https://ghfast.top/",
	"https://gh-proxy.com/",
	"https://ghproxy.net/",
	"", // GitHub 官方
}

func main() {
	projectRoot, err := os.Getwd()
	if err != nil {
		fatal("获取当前目录失败: %v", err)
	}

	// 如果从 exe 所在目录运行，使用 exe 所在目录
	exePath, err := os.Executable()
	if err == nil {
		exeDir := filepath.Dir(exePath)
		// 如果 exe 在项目根目录（有 pyproject.toml），使用 exe 所在目录
		if _, err := os.Stat(filepath.Join(exeDir, "pyproject.toml")); err == nil {
			projectRoot = exeDir
		}
	}

	uvDir := filepath.Join(projectRoot, ".uv")
	uvExe := filepath.Join(uvDir, "uv.exe")

	// 解析参数
	installOnly := false
	noPause := false
	var extraArgs []string
	for _, arg := range os.Args[1:] {
		switch arg {
		case "--install-only":
			installOnly = true
		case "--no-pause":
			noPause = true
		default:
			extraArgs = append(extraArgs, arg)
		}
	}

	// 查找 uv
	uvCmd := findUv(uvDir, uvExe)
	fmt.Printf("使用 uv: %s\n", uvCmd)

	// [1/3] 安装依赖
	fmt.Println("\n[1/3] 安装依赖...")
	if err := runCommand(uvCmd, "sync"); err != nil {
		fmt.Printf("[X] 依赖安装失败: %v\n", err)
		fmt.Println("    手动运行: uv sync")
		fmt.Println("    如 uv.lock 损坏: uv lock --upgrade")
		pause(noPause)
		os.Exit(1)
	}

	// [2/3] 安装 Playwright Chromium
	fmt.Println("\n[2/3] 安装 Playwright Chromium...")
	if err := runCommand(uvCmd, "run", "playwright", "install", "chromium"); err != nil {
		fmt.Println("[!] Playwright 安装失败，如已安装可忽略")
		fmt.Println("    手动运行: uv run playwright install chromium")
	}

	// 检查 --install-only
	if installOnly {
		fmt.Println("\n[OK] 环境准备完成")
		return
	}

	// [3/3] 启动应用
	fmt.Println("\n[3/3] 启动 Campus-Auth...")
	args := append([]string{"run", "main.py", "--browser"}, extraArgs...)
	if err := runCommand(uvCmd, args...); err != nil {
		fmt.Printf("[X] 启动失败: %v\n", err)
		pause(noPause)
		os.Exit(1)
	}
}

// findUv 查找 uv 命令：PATH → 本地 .uv → 下载
func findUv(uvDir, uvExe string) string {
	// 1. 检查 PATH
	if path, err := exec.LookPath("uv"); err == nil {
		return path
	}

	// 2. 检查本地 .uv 目录
	if _, err := os.Stat(uvExe); err == nil {
		return uvExe
	}

	// 3. 下载
	if err := downloadUv(uvDir, uvExe); err != nil {
		fatal("[X] uv 下载失败: %v", err)
	}
	return uvExe
}

// downloadUv 从镜像源下载 uv（使用系统 curl 和 tar）
func downloadUv(uvDir, uvExe string) error {
	// 检查必要工具
	if _, err := exec.LookPath("curl"); err != nil {
		return fmt.Errorf("需要 curl 命令\n    请手动安装 uv: https://docs.astral.sh/uv/")
	}
	if _, err := exec.LookPath("tar"); err != nil {
		return fmt.Errorf("需要 tar 命令（Windows 10 1803+ 自带）\n    请手动安装 uv: https://docs.astral.sh/uv/")
	}

	uvFilename := getUvFilename()
	githubURL := "https://github.com/astral-sh/uv/releases/download/" + uvVersion + "/" + uvFilename

	fmt.Printf("正在下载 uv %s (%s)...\n", uvVersion, runtime.GOARCH)

	if err := os.MkdirAll(uvDir, 0755); err != nil {
		return fmt.Errorf("创建目录失败: %v", err)
	}

	archive := filepath.Join(uvDir, "uv.zip")

	for _, mirror := range mirrors {
		url := mirror + githubURL
		if mirror == "" {
			fmt.Println("  尝试: GitHub 官方")
		} else {
			fmt.Printf("  尝试: %s\n", mirror)
		}

		// 使用 curl 下载
		cmd := exec.Command("curl", "-fsSL", "--connect-timeout", "10", "--max-time", "120", "-o", archive, url)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			os.Remove(archive)
			continue
		}

		// 校验 zip 文件有效性（用 tar 测试）
		cmd = exec.Command("tar", "-tf", archive)
		cmd.Stdout = nil
		cmd.Stderr = nil
		if err := cmd.Run(); err != nil {
			fmt.Println("  [!] 文件无效，尝试下一个源...")
			os.Remove(archive)
			continue
		}

		// 解压
		fmt.Println("正在解压...")
		cmd = exec.Command("tar", "-xf", archive, "-C", uvDir)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			os.Remove(archive)
			return fmt.Errorf("解压失败: %v", err)
		}
		os.Remove(archive)

		if _, err := os.Stat(uvExe); err != nil {
			return fmt.Errorf("解压后未找到 uv.exe")
		}

		fmt.Println("[OK] uv 下载完成")
		return nil
	}

	return fmt.Errorf("所有下载源均失败\n    请手动安装 uv: https://docs.astral.sh/uv/")
}

// runCommand 运行外部命令，实时输出
func runCommand(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// fatal 输出错误信息并退出
func fatal(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

// pause 等待用户按键（CI 环境或 noPause=true 时跳过）
func pause(noPause bool) {
	// 检测 CI 环境变量
	if os.Getenv("CI") != "" || os.Getenv("GITHUB_ACTIONS") != "" || noPause {
		return
	}
	fmt.Print("\n按回车键继续...")
	fmt.Scanln()
}
