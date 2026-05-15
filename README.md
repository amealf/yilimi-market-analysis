# Yilimi Market Analysis

这个仓库发布一个自动更新的 GitHub Pages 静态站点。

当前栏目：

- A股融资融券
- 加密市场流动性：BTC/ETH 价格与 USDT/USDC 发行量

本地生成：

```powershell
python scripts\build_site.py --all
```

GitHub Actions 会在每天 CST 00:00 和 12:00（UTC+8，中国标准时间）运行，并发布 `site` 目录到 GitHub Pages。
