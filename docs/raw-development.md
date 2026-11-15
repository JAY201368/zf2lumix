# RAW 显影后端

`converter/raw_developer/` 提供独立的 Python / Swift / Metal 实现。入口为 `Developer.render`（RW2）和 `Developer.render_file`（NEF/RW2），支持照片格调、最多两层 33³ `.cube` LUT、逐层浓度及 JPEG 导出。

## 运行条件

本模块需要 macOS Metal、Swift 编译器、本机安装的 LUMIX Lab 格调资源，以及 `raw_developer/nr-parameter-curves.json` 校准数据。NR 校准数据和原厂资源保留在本地环境，公开仓库提供实现源码。资源缺失时会报错。公开桌面版的操作入口为 NEF → RW2。

默认资源位置为 `/Applications/LUMIX Lab.app/Wrapper/LUMIXLab.app`，可通过 `--bundle` 或 `Developer(bundle=...)` 指定。后端读取原厂资源及哈希锁定的校准数据区，独立执行图像处理。

## 接口

在资源齐备的本地环境，从仓库根目录运行。输出目录需已存在。

```sh
PYTHONPATH=converter python3 -m raw_developer /path/to/input.NEF \
  -o /path/to/output --style natural \
  --lut /path/to/first.cube --strength 0.37 \
  --lut /path/to/second.cube --strength 0.63
```

`--sharpness` 与 `--noise-reduction` 为 0–100，默认 50。`--quality` 为 1–100，默认 95。LUT 浓度范围 0–1，省略时为 1。

```python
from pathlib import Path
from raw_developer import Developer, RenderOptions, LUTLayer

report = Developer().render_file(
    Path('/path/to/input.NEF'),
    Path('/path/to/output'),
    RenderOptions(
        photo_style='natural',
        luts=(LUTLayer(Path('/path/to/look.cube'), 0.5),),
    ),
)
```

## 输出与验证

JPEG 使用 4:4:4 编码，嵌入 sRGB ICC，按裁切与方向生成最终像素。NEF 转换成功后即保留 RW2 及记录，后续 JPEG 导出失败时可继续使用这些文件。

2026-11-01 的本地验证覆盖真实 ISO800 NEF → RW2 → 自然格调 JPEG、转换 RW2 重新打开、ISO6400 V-Log 及 ISO100 自然格调双 LUT。

中性镜头策略依据与内容哈希匹配的转换记录识别。移动转换后的 RW2 时一并保留 JSON 记录，缺失记录时可显式选择 `--no-lens-correction`。

资源与许可说明见 [第三方声明](../converter/THIRD_PARTY_NOTICES.md)。
