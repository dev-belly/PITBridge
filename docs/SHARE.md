# Share the invoice counterexample

## 中文

做金融数据或特征工程时，事后修订容易被误用到历史决策。我做了 [PITBridge](https://github.com/dev-belly/PITBridge)：用合成发票说明，同为2026年1月31日数据，v1于2月5日发布、6日入库，值10万元；v2于4月1日发布、3日入库，值13.5万元。90天新鲜度下，2月1日未可用，2月15日选v1，4月15日选v2；SQL与独立Python逐行核对。[小示例](https://github.com/dev-belly/PITBridge/blob/main/examples/README.md)可本地运行；[在线演示](https://dev-belly.github.io/PITBridge/)展示11条观测、45次查询的大案例。想请你试试CSV输入，反馈时点与修订选择是否贴合你的场景：[提交反馈](https://github.com/dev-belly/PITBridge/issues/new?template=trial_feedback.md)。

## English

Working with financial data or features? [PITBridge](https://github.com/dev-belly/PITBridge) explores which observations were actually available at a historical decision time. A synthetic invoice example has two versions for January 31, 2026: v1 is published February 5, ingested February 6, and worth CNY 100,000; v2 is published April 1, ingested April 3, and worth CNY 135,000. With a 90-day freshness limit, February 1 is `not_available`, February 15 selects v1, and April 15 selects v2. SQL results are checked row by row against an independent Python implementation. The [small example](https://github.com/dev-belly/PITBridge/blob/main/examples/README.md) runs locally; the [online demo](https://dev-belly.github.io/PITBridge/) shows a larger case with 11 observations and 45 queries. Please try the optional CSV input and [share feedback](https://github.com/dev-belly/PITBridge/issues/new?template=trial_feedback.md) on timestamp handling and revision selection in your workflow.

## Run locally / 本地运行

First follow the [quick start](../README.md#run-in-one-minute) to install the
project in `.venv`. From the repository root, run:

先按[快速开始](../README.md#run-in-one-minute)安装项目到 `.venv`，然后在仓库根目录运行：

**Linux / macOS**

```bash
.venv/bin/python examples/decision_time.py
```

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\python.exe examples\decision_time.py
```

Python 3.11+ is required. The core project and this example use only the standard
library. The [CSV example](../examples/README.md#optional-pandascsv-input)
requires the optional pandas dependency.

需要 Python 3.11+。核心项目与上述小示例仅使用标准库；[CSV 示例](../examples/README.md#optional-pandascsv-input)需另装可选依赖 pandas。
