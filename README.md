# a23_ai_demo

一个面向**报表自动抽取与模板回填**的本地化项目，支持：

- 根据 **Excel / Word 模板** 自动生成 profile
- 从原始文档或 RAG 中间结果中抽取信息
- 支持两类任务：
  - `single_record`：单条表单/合同类
  - `table_records`：多行表格类
- 支持三种模板写回方式：
  - `vertical`：Excel 竖版键值表
  - `excel_table`：Excel 多行表格
  - `word_table`：Word 多行表格
- 输出统一调试与汇总文件 `report_bundle.json`

---

## 1. 项目功能概览

当前主流程由 `main.py` 驱动：

1. 根据模板自动生成 profile
2. 读取原始文档（可选）
3. 读取 RAG 中间 JSON（可选）
4. 根据 profile 构造 prompt 并调用本地模型
5. 做规则后处理 / 缺失检查 / 表格规则补齐
6. 将结果写入 Excel / Word 模板
7. 生成 `result.json`、模板结果文件、`report_bundle.json`

---

## 2. 目录结构

```text
a23_ai_demo/
├─ main.py                      # 主入口：自动生成 profile + 抽取 + 填表
├─ auto_profile.py              # 单独生成 profile 的命令行入口
├─ regression_runner.py         # 回归测试脚本（当前需同步适配新版 main.py）
├─ profiles/                    # profile 配置 / 自动生成的 profile
├─ src/
│  ├─ config.py                 # Ollama 地址、模型名、输出常量
│  ├─ auto_profile/
│  │  ├─ template_detector.py   # 模板结构识别
│  │  ├─ alias_resolver.py      # 字段别名归一化 / RapidFuzz 模糊匹配
│  │  ├─ field_inferer.py       # 字段类型/格式/required 推断
│  │  ├─ instruction_builder.py # 自动生成 instruction
│  │  └─ profile_generator.py   # 组装 profile
│  ├─ engine/
│  │  ├─ document_reader.py     # 读取 txt / md / docx
│  │  ├─ prompt_builder.py      # prompt 构造
│  │  ├─ retrieval_client.py    # RAG 片段格式化与辅助
│  │  ├─ model_client.py        # 调用 Ollama
│  │  ├─ postprocess.py         # 规则处理 / 格式化 / 缺失处理
│  │  └─ writers.py             # Excel / Word 模板写回
│  ├─ ocr/
│  │  └─ layout_parser.py       # OCR / 版面分析预留入口（暂未实现）
│  └─ schemas/
│     └─ field_aliases.json     # 字段别名表
├─ data/
│  ├─ template/                 # 模板文件
│  ├─ in/                       # 原始文档
│  └─ rag_input/                # RAG 中间 JSON（建议）
└─ output/                      # 输出目录
```

---

## 3. 环境要求

- Python 3.10+
- 本地已安装并运行 [Ollama](https://ollama.com/)
- 默认模型配置位于 `src/config.py`

当前默认配置：

```python
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "llama3.1"
TARGET_LIMIT_SECONDS = 90
```

如需切换模型，直接修改 `src/config.py`。

---

## 4. 安装依赖

先创建虚拟环境，再安装依赖：

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

---

## 5. main.py 如何使用

### 5.1 仅模板 + 原始文档

适合完整链路测试：

```bash
python main.py --template data/template/template.xlsx --input-dir data/in
```

### 5.2 模板 + 原始文档 + RAG JSON

适合“RAG 缩小范围，你再抽取”的协作方式：

```bash
python main.py --template data/template/template.xlsx --input-dir data/in --rag-json data/rag_input/test.json
```

### 5.3 模板 + RAG 结构化结果直灌

适合只测你这边的下游填表能力：

```bash
python main.py --template data/template/template.xlsx --rag-json data/rag_input/test.json --prefer-rag-structured
```

### 5.4 启用本地模型增强 profile 生成

```bash
python main.py --template data/template/template.xlsx --input-dir data/in --use-profile-llm
```

### 5.5 指定输出目录

```bash
python main.py --template data/template/template.xlsx --input-dir data/in --output-dir output/test_run_01
```

---

## 6. auto_profile.py 如何使用

只测试模板 → profile 自动生成：

```bash
python auto_profile.py --template data/template/template.xlsx
```

指定输出位置：

```bash
python auto_profile.py --template data/template/template.xlsx --output profiles/template_auto.json
```

启用本地模型辅助字段推断：

```bash
python auto_profile.py --template data/template/template.xlsx --use-llm
```

---

## 7. 输入建议

### 模板文件
放在：

```text
data/template/
```

### 原始文档
放在：

```text
data/in/
```

### RAG 中间结果
建议放在：

```text
data/rag_input/
```

推荐的 RAG JSON 结构至少包含以下之一：

#### 方式 A：提供检索片段
```json
{
  "retrieved_chunks": [
    {
      "text": "……",
      "score": 0.98,
      "position": "第1段",
      "source": "xxx.docx"
    }
  ]
}
```

#### 方式 B：直接提供结构化结果
```json
{
  "result": {
    "records": [
      {
        "城市名": "上海",
        "GDP总量（亿元）": "56708.71"
      }
    ]
  }
}
```

---

## 8. 输出文件说明

运行后通常会生成：

- `result.json`：最终抽取结果
- `result.xlsx`：填写后的 Excel 模板
- `result.docx`：填写后的 Word 模板（若模板为 Word）
- `report_bundle.json`：运行摘要、耗时、调试、证据等汇总信息

`report_bundle.json` 主要包含：

- `meta`
- `run_summary`
- `runtime_metrics`
- `debug_result`
- `retrieval`
- `field_evidence`

---

## 9. 任务模式说明

### 9.1 single_record
适用于合同、表单、单条信息抽取。

输出示例：

```json
{
  "项目名称": "智能仓储巡检平台",
  "甲方单位": "福州云帆科技有限公司",
  "签订日期": "2026年3月15日"
}
```

### 9.2 table_records
适用于空气质量表、城市榜单、批量记录表格。

输出示例：

```json
{
  "records": [
    {
      "城市名": "上海",
      "GDP总量（亿元）": "56708.71"
    },
    {
      "城市名": "北京",
      "GDP总量（亿元）": "49843.10"
    }
  ]
}
```

---

## 10. 规则补齐策略

当前建议：

- `single_record`：允许缺字段后二次补抽
- `table_records`：优先规则补齐，不走通用大模型逐行补抽

这是为了避免表格任务中出现“补错行、串行、幻觉填值”的问题。

---

## 11. 已知注意事项

### 11.1 regression_runner.py 需要同步适配新版 main.py
当前 `main.py` 已改成以 `--template` 为主入口，而 `regression_runner.py` 如果仍传 `--profile`，需要你后续同步更新。

### 11.2 OCR / PDF / 图片识别尚未接入
`src/ocr/layout_parser.py` 目前只是预留入口，暂未实现真正 OCR/版面分析。

### 11.3 document_reader.py 当前主要支持
- `.txt`
- `.md`
- `.docx`

如果后续要接 PDF / 图片，需要扩展 OCR / layout parser 链路。

---

## 12. 当前推荐测试命令

### 测模板自动生成 + 主流程 + 下游填表
```bash
python main.py --template data/template/2025年中国城市经济百强全景报告-模板.xlsx --rag-json data/rag_input/2025年中国城市经济百强全景报告_rag中间转换.json --prefer-rag-structured --output-dir output/test_run_01
```

### 测模板自动生成
```bash
python auto_profile.py --template data/template/2025年中国城市经济百强全景报告-模板.xlsx --use-llm
```

---

## 13. requirements 说明

本项目 Python 侧核心依赖为：

- `requests`
- `python-docx`
- `openpyxl`
- `rapidfuzz`

其余如 `json`、`argparse`、`pathlib`、`decimal`、`re`、`csv`、`shutil`、`subprocess`、`sys` 等均为标准库。

---

## 14. 后续扩展建议

后续可以继续补：

- OCR / PDF 识别
- 字段别名语义向量匹配
- 表格逐行片段补抽
- 更稳健的回归测试
- profile 草稿自动缓存
