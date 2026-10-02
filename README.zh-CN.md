# PITBridge｜金融时点数据与版本溯源

**核心问题：做出信贷决策时，银行当时到底能看到哪个版本的数据？**

例如，一月份开票金额在二月份公开、三月份才进入银行系统，四月份又被修订。直接按照“一月份”去关联历史申请，会把后来的信息放进早期特征，导致回测过于乐观。

PITBridge 同时处理数据发生时间、公开时间、入库时间和修订版本；以 SQLite SQL 生成特征，用独立 Python 枚举结果核验，并保留每一个特征的来源记录。

![保存结果的可复现图表](docs/evidence.png)

## 快速运行

```bash
python -m pip install -e .
pitbridge demo --out outputs
pitbridge verify --out outputs
python -m unittest discover -s tests -v
```

打开 `outputs/report.html` 即可查看离线报告。需要 Python 3.11 或更高版本，无第三方运行依赖。

## 已实现的重点

- **防止未来信息泄漏：** 数据发生时间与真正可用时间都必须不晚于申请时间。
- **正确处理修订：** 选择当时已知的最高版本；迟到的旧版本不会覆盖新版本。
- **撤销与过期：** 撤销记录只影响对应观察时点，不能重新使用该记录旧版本；特征可配置有效天数。
- **显式缺失：** 区分没有历史、尚未可用、已撤销和已过期，保留申请行。
- **逐条溯源：** 导出来源、记录 ID、版本、发生时间、公开时间与入库时间。
- **可重放证据：** 修改报告并更新哈希，仍会被语义重放发现。
- **时点滚动统计：** 在选择当时已知版本后，计算指定窗口的加总、观察均值和计数，并保留每条贡献记录；SQL 与 Python 分别重放成员与数值。

[在线滚动特征案例](https://dev-belly.github.io/PITBridge/rolling/) · [窗口合同与手算案例](docs/ROLLING.md)

```bash
pitbridge rolling-demo --out outputs/rolling
pitbridge verify-rolling --out outputs/rolling
```

合成示例有 11 条源记录、15 次决策、45 次特征查询。错误的“只按发生时间关联”基线有 11 次使用未来信息；完整规则共改变 16 次选择。后者还包括撤销和过期影响，不能把两个数字混为一谈。

[方法与规则](docs/METHODOLOGY.md) · [输入字段](docs/DATA_CONTRACT.md) · [中文面试问答及简历表述](docs/INTERVIEW.md)

这是可以核验的金融数据工程研究组件。演示数据全部为合成；没有宣称接入真实银行、降低实际违约率或处理生产规模数据。
