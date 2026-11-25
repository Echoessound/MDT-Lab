# ACRIN 6668 纵向肺癌本地样本

ACRIN 6668 是局部晚期非小细胞肺癌的多中心前瞻性研究，记录了放化疗前后 FDG-PET 检查、本地判读和临床随访。TCIA 将去标识临床表与影像分别发布。此样本取自临床第 1 组，下载量为 276,286 字节，许可为 CC BY 3.0。[官方队列](https://www.cancerimagingarchive.net/collection/acrin-nsclc-fdg-pet/) · [临床 ZIP](https://www.cancerimagingarchive.net/wp-content/uploads/ACRIN-6668-NSCLC-FDG-PET-ACRIN-Data-TCIA-Anonymized-File-set-1.zip) · [许可](https://creativecommons.org/licenses/by/3.0/)

从第 1 组的 189 个登记号按数值升序取前 12 例，保留入组登记、本地 PET、放疗、F1 随访四张表中符合映射的记录。固定抽样不使用结局、完整度和模型输出。转换后的 [local_sample.json](local_sample.json) 为 122,105 字节，含 121 个事件，包括 40 个检查或判读节点、22 个放疗节点、43 个收到随访表的节点，以及 16 个登记或未完成记录节点。同一份表的检查和判读可形成两个节点。一例可有多份随访表。

## 导入和复算

在工作台「数据导入」选择研究 JSON，上传本目录的 `local_sample.json`，将上限设为 12，预检后提交。命令行可在 `mdt-demo` 下执行以下命令。若工作台已运行，优先通过工作台提交，确保写入当前服务使用的存储。

```sh
.venv/bin/python scripts/import_dataset.py research_json data/acrin_6668/local_sample.json --max-cases 12 --commit
```

若需从官方原表复算，可用以下命令生成对照文件。转换器在读表前校验原包 SHA-256，输出可与随附文件按字节比较。

```sh
curl -fLsS 'https://www.cancerimagingarchive.net/wp-content/uploads/ACRIN-6668-NSCLC-FDG-PET-ACRIN-Data-TCIA-Anonymized-File-set-1.zip' -o /tmp/acrin_6668_set1.zip
.venv/bin/python scripts/build_acrin_6668_sample.py /tmp/acrin_6668_set1.zip /tmp/acrin_6668_sample.json
cmp /tmp/acrin_6668_sample.json data/acrin_6668/local_sample.json
```

## 字段和时间

以源 ZIP 内的 `QIN_6668 Data Dictionary.xls` 为字段依据。研究包中的每个事件都有原表名、行号和源列映射。界面上的日期等于 TCIA 公共基准日 1960-01-01 加原表偏移天数，保留负偏移。同日事件的编号顺序仅用于重放。年龄取 `A0.entryage`，性别取 `A0.a0e11`。

| 来源 | 可见时点 | 可引用资料 |
| --- | --- | --- |
| A0 入组表 | `A0e17d` 登记日 | 病理证实 NSCLC 及临床分期是否属于 IIB/III 的登记项 |
| IM 本地 PET 表 | `IMe10d` 检查日，`IMe11d` 判读日 | 检查完成情况和治疗前后阶段；直到判读时才加入影像质量和有记录的肺部 SUVpeak（`ime18` / `ime43`） |
| T1 放疗表 | `T1e2d` 首次、`T1e3d` 末次放疗日 | 已记录的放疗开始与末次治疗 |
| F1 随访表 | `rec` 研究中心收表日 | 最近评估的偏移日及有记录的进展评估 `f1e8` |
| IM/T1 未完成记录 | `rec` 收表日 | 仅在原表明确填“否”时生成 |

PET 与放疗按当地事件日期回放；F1 收表前不显示该表的进展状态。入组病理证实、PET 完成和整个检查报告齐备是不同的事实。此样本不含原始影像、病理报告全文、测序结果或人工 MDT 就绪度标签。它可用于测试资料出现先后、冻结边界与引用追溯，正式效果评估需另行独立标注和抽样。

例如，`ACRIN-6668-005` 在相对第 0 天完成 PET、第 16 天才有本地判读。回到检查截点，只应能引用检查记录。另一个病例 `ACRIN-6668-011` 有研究中心收到的 PET 未完成记录，可检查同一病例既有已完成检查、又有另一次未完成记录时的证据呈现。

## 署名与版本

Kinahan P, Muzi M, Bialecki B, Herman B, Coombs L (2019). *Data from the ACRIN 6668 Trial NSCLC-FDG-PET (Version 2)*. The Cancer Imaging Archive. 本项目的改动包括限定病例和列、翻译编码、将相对日期映射到项目时间轴以及转换为 Research JSON。[数据 DOI](https://doi.org/10.7937/tcia.2019.30ilqfcl)

- 映射版本 `acrin-6668-v1`
- 源 ZIP SHA-256 `f788dd16488900a3aab35b2c24699e5c2841aa8031e928a8fced9d8edf0ab8ee`
- 导入 JSON SHA-256 `996f5bb241aab8e6acd6cb7c3e31bfb61381bf74b3457325d32e5bc7c0fb883c`
