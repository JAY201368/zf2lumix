# 使用与构建

Zf2Lumix 1.0.1 将 Nikon Zf 的 14 位 NEF 转为 S5M2 兼容 RW2。桌面版采用 neutral 镜头策略，保留原片，逐张输出 RW2 与 JSON 转换记录。

## 桌面操作

| 操作 | 入口 |
| --- | --- |
| 导入 NEF / 文件夹 | 「导入」、拖放，或 ⌘/Ctrl + O |
| 选择照片 | 单击，多选用 ⌘/Ctrl，连续选择用 Shift |
| 移出队列 | 右键菜单或 Backspace / Delete |
| 撤销最近一次移除 | 「撤销移除」或 ⌘/Ctrl + Z |
| 查看照片详情 | 双击照片或右键菜单 |
| 查看冲印记录 | 胶片上方纸签或 ⌘/Ctrl + I |
| 开始转换 | 「转换」或 ⌘/Ctrl + Enter |
| 收起记录或详情 | 「收起」或 Escape |

「清空」清除当前导入队列。转换结束后的首次有效导入开始新批次。取消导入保留上一批记录。关闭正在转换的窗口时，程序先完成当前照片，再停止后续队列。

旋钮支持单击左右、拖动、滚轮和键盘方向键，释放后吸附到自动、日光或暖光挡位。自动模式依据拍摄白平衡选择或混合校准。转换期间参数锁定，胶片跟随真实处理进度。

## 格式与文件

- 输入为 Nikon Zf 的 14 位 RGGB NEF。保留曝光时间、拍摄日期、方向、ISO、光圈与焦距等元数据。
- 全幅有效输出为 6000 × 4000。4032 × 4032 的源裁切输出 4000 × 4000，其他裁切按同一比例与偶数 Bayer 对齐规则处理。
- RW2 内部使用 6008 × 4008 编码外壳，通过传感器边界和裁切字段定义有效画面。忽略裁切元数据的软件可能显示外侧延展像素。
- 同名输出使用数字后缀另存。每张照片附带 JSON，记录源文件与输出哈希、裁切、校准及警告。
- 写入后执行两轮 LibRaw 全样本与裁切回读。使用输出盘内临时文件及硬链接完成发布，输出盘须支持硬链接。
- ISO 校准覆盖 100–12800。中间档采用 log2 ISO 插值，ISO800 使用已验证的 400/1600 插值，范围外使用边界参数并记录警告。

## 兼容性与验证范围

macOS 下载包针对 Apple Silicon，采用本地签名。Apple Developer ID 公证待完成。Windows x64 提供构建脚本及源码，EXE 实机验证待完成。

既有 LUMIX Lab 对照覆盖四张 ISO800 样本的标准格调及相同显影设置。当前实现的裁切、白平衡推断、自动光源插值及元数据路径已做本地检查，对应 Lab 实际显影验收仍待完成。项目沿用颜色映射可推广的工作假设。

内嵌 JPEG 预览使用 LibRaw 生成，最终颜色以目标软件实际显影为准。默认 neutral 策略关闭模板畸变和暗角参数，Nikon 镜头校正需由后续处理软件承担。

## 开发与构建

macOS 需要 Python 3.12、可用的 Tk 和 C++ 编译器。从仓库根目录进入 `converter/`。

```sh
cd converter
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
clang++ -std=c++17 -O3 encode_pana8.cpp -o encode_pana8
.venv/bin/python app.py
```

命令行可接受一个或多个文件、文件夹。

```sh
.venv/bin/python converter.py /path/to/photos -o /path/to/output \
  --profile auto --lens-policy neutral
```

公开桌面版构建使用随附 profiles、已清理模板及 NEF → RW2 界面资源。

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_core.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_template_assets.py' -v
.venv/bin/pyinstaller --noconfirm Zf2Lumix-desktop.spec
```

生成 `dist/Zf2Lumix.app`。Windows 的工具链与打包步骤见 [WINDOWS.md](../converter/WINDOWS.md)。

| 模块 | 职责 |
| --- | --- |
| `app.py` | 桌面界面、批次队列、后台转换 |
| `filmstrip.py` | 胶片、多选、滚动与缩略图 |
| `batch_card.py` | 纸质记录、检片详情与定位 |
| `retro_ui.py` / `camera_controls.py` | 材质、LCD、旋钮与转换键 |
| `converter.py` | 校准、转换、回读验证与输出 |
| `rw2.py` / `encode_pana8.cpp` | 元数据、RAW 编码与 RW2 组装 |
| `template_assets.py` | 兼容模板清理 |

### RAW 显影后端

`converter/raw_developer/` 保留独立的 Swift / Metal / Python 显影实现，包含照片格调、两层 LUT 与 JPEG 导出接口。运行需要另行具备原厂格调资源和未随仓库分发的 NR 校准数据。公开桌面下载包提供 NEF → RW2 功能，显影控件仍待接入。接口及环境说明见 [后端说明](raw-development.md)。

`Zf2Lumix.spec` 保留包含显影后端的本地整包配置，公开桌面构建使用 `Zf2Lumix-desktop.spec`。

## 许可与来源

[MIT](../LICENSE) 覆盖原创代码与项目拟合参数。随附兼容模板清理了供体序列号、时间、自由文本及图像像素。依赖许可、字体及资源边界见 [第三方声明](../converter/THIRD_PARTY_NOTICES.md)。
