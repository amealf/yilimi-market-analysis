# Yilimi Market Analysis

这个仓库发布一个自动更新的 GitHub Pages 静态站点。

当前栏目：

- A股融资融券
- 加密市场流动性：BTC/ETH 价格与 USDT/USDC 发行量
- 全球利率：美国、日本、韩国、英国30Y国债收益率日内变化

本地生成：

```powershell
python scripts\build_site.py --all
```

全球30Y国债收益率历史分钟缓存：

```powershell
python global_30y_bond_intraday\cli.py --download-year 2026
```

GitHub Actions 会在每天 CST 00:00 和 12:00（UTC+8，中国标准时间）运行，并发布 `site` 目录到 GitHub Pages。
