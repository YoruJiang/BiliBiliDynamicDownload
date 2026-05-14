# BiliBiliDynamicDownload

下载哔哩哔哩 up 主所有动态中的图片。

## 使用方法

```shell
git clone https://github.com/YoruJiang/BiliBiliDynamicDownload.git
cd BiliBiliDynamicDownload
pip install -r requirement.txt
python main.py <uid> [--path PATH] [--login] [--delay DELAY] [--concurrency N] [--page-delay DELAY]
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uid` | up 主的 UID（必填） | - |
| `--path` | 图片保存路径 | `./pics` |
| `--login` | 强制重新扫码登录 | - |
| `--delay` | 图片下载间隔（秒） | `0.3` |
| `--concurrency` | 并发下载数 | `3` |
| `--page-delay` | 翻页间隔（秒） | `1.5` |

## 关于登录

B 站未登录状态下无法获取全部动态。首次运行时会提示是否使用二维码登录：

- 输入 `y`，终端显示二维码，用 B 站 App 扫码即可登录
- 登录凭证会保存在本地，下次运行无需重复扫码
- 输入 `N` 则跳过登录继续运行（可能无法获取全部动态）

## 示例

```shell
# 基本用法
python main.py <uid>

# 指定保存路径
python main.py <uid> --path ./downloads

# 被限流时可以降低请求频率
python main.py <uid> --delay 0.5 --concurrency 2 --page-delay 3
```
