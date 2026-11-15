# Zf2Lumix Windows x64

目标平台：Windows 10/11 x64（Intel / AMD）。Windows ARM64 原生版本未提供。

当前交付是 Windows 适配源码与构建包，不是已经生成的 EXE。开发机为 macOS，无 Windows 虚拟机；Windows 实机打包、启动和完整转换尚待执行。现有 macOS 成品保留。

## 在 Windows 生成应用

只需在构建电脑安装一次：

1. Python 3.12 **64 位**，安装时包含 pip、venv、Tcl/Tk 和 Python Launcher。
2. Visual Studio 2022 Build Tools，选择「使用 C++ 的桌面开发」，包含 MSVC x64 工具及 Windows SDK。
3. 将本包解压到本地 NTFS 磁盘。双击 `build-windows.cmd`。首次构建会联网安装锁定版本的 Python 依赖。构建时会从官方 SourceForge 下载 ExifTool 13.59 x64，连同 Perl 运行库一起打包，无需另装 Perl。下载失败时可按文末说明手动放置。

构建完成得到 `dist/Zf2Lumix-Windows-x64.zip`。把它复制给使用者；解压后双击其中 `Zf2Lumix.exe`。必须保留整个文件夹，包括 `_internal`。使用者不需要 Python、Perl、编译器或联网。

若要同时执行真实照片验收，在终端运行：

```powershell
py -3.12 windows/build.py --sample "D:\照片\样本.NEF"
```

构建脚本会编译原生 x64 编码器、运行单元测试、打包，并将成品搬到含中文和空格的临时路径，检查窗口创建、模板、ExifTool、编码器。提供 NEF 后还会转换两次，检查全部 24,080,064 个 RAW 样本回读、同名另存与原片哈希。验收记录随成品保存为 `windows-validation.json`；没有提供 NEF 时会明确记录完整转换未验证。

## 使用

添加照片或文件夹，选择输出位置，点击「开始转换」。快捷键为 Ctrl+O / Ctrl+Enter。输出必须位于支持硬链接的磁盘（建议本地 NTFS）；exFAT/FAT32 不支持这里的安全保存方式。默认算法、校准和 RW2 结构与 macOS 源码相同。

命令行入口：

```powershell
.\Zf2Lumix.exe --cli "D:\照片" -o "D:\输出"
```

这是窗口应用，命令行不保证显示控制台日志；每张照片的 JSON 包含转换与校验记录，退出码表示成功或失败。

## 仓库布局

从仓库的 `converter/` 目录运行 `build-windows.cmd`。公开仓库随附 Python 源码、编码器 C++ 源码、profiles 及已清理的兼容模板。

## ExifTool 来源

Windows 包使用官方 ExifTool 13.59 x64，来源：
https://exiftool.org/ （Windows 64-bit 下载）
https://sourceforge.net/projects/exiftool/files/exiftool-13.59_64.zip/download

如缺失：将官方 ZIP 内的 `exiftool(-k).exe` 改名为 `exiftool.exe` 放入 `vendor/`，同时将完整 `exiftool_files/` 放在其旁边。许可见该目录及 `THIRD_PARTY_NOTICES.md`。Windows 与 macOS 的 ExifTool 版本不同，实际 Windows NEF 转换需要上述样本验收。
