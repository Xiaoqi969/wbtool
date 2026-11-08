# assets / 资源文件说明

> 文件说明：本目录存放程序的图标资源，逐文件说明来源与用途。

| 文件 | 用途 | 说明 |
|---|---|---|
| `wbtool.ico` | exe 程序图标 | WorkBuddy 官方应用图标，含 16×16 至 256×256 共 11 种尺寸，32 位色。供 `build.py` 的 `--icon` 使用。 |
| `wbtool-256.png` | README 展示用小 logo | 由同一官方图标缩放而来（256×256），避免仓库塞入原尺寸大图。 |

## 图标来源与声明

图标取自 WorkBuddy 官方应用安装包内的应用图标资源（PNG 与多尺寸 ICO），
即 WorkBuddy 官方应用 logo，用于标识「本工具读取 WorkBuddy 的会话数据」。

- 该图标**不属于**本项目的 MIT 许可证范围，版权归原权利人所有。
- 本项目是非官方的个人工具，与 WorkBuddy 官方无隶属或背书关系。
- 若权利方对图标使用有异议，请删除 `assets/wbtool.ico` 并在 `build.py` 中去掉 `--icon` 参数，
  或替换为自行绘制的图标；程序功能不受影响。

## 替换图标

准备一个含多尺寸的 `.ico` 覆盖 `assets/wbtool.ico`，再运行 `python build.py` 重新打包即可。
可用 Pillow 生成：

```python
from PIL import Image
im = Image.open("my-logo.png")
im.save("assets/wbtool.ico", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
```
