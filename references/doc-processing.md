# 文档处理协作指南

本skill在需要处理PDF/Excel等文档时，调用「文档处理套件」的能力。

---

## 何时需要文档处理

| 场景 | 处理方式 |
|-----|---------|
| 用户上传PDF基金季报 | 提取文本后分析 |
| 需要批量处理Excel持仓数据 | 转CSV后分析 |
| 从下载文件夹读取多个文档 | 批量提取 |

---

## PDF提取（基金季报专用）

```python
import pdfplumber
import os

def extract_fund_report(pdf_path, max_pages=15):
    """
    提取基金季报/年报核心内容
    通常前15页包含：基金概况、主要财务指标、净值表现、投资组合、管理人报告
    """
    if not os.path.exists(pdf_path):
        return None, "文件不存在"
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            total_pages = min(len(pdf.pages), max_pages)
            
            for i in range(total_pages):
                page_text = pdf.pages[i].extract_text()
                if page_text:
                    text += f"\n--- 第{i+1}页 ---\n"
                    text += page_text
            
            return text, f"成功提取{total_pages}页"
    except Exception as e:
        return None, f"提取失败: {str(e)}"

# 使用示例
# text, msg = extract_fund_report("/Users/.../基金季报.pdf")
```

---

## 关键信息定位

基金季报通常包含以下章节，提取时优先关注：

| 章节 | 页码范围 | 关键信息 |
|-----|---------|---------|
| 基金产品概况 | 第1-2页 | 基金代码、类型、规模、费率 |
| 主要财务指标 | 第2-3页 | 本期利润、净值增长率 |
| 基金净值表现 | 第3-4页 | 与基准对比、超额收益 |
| 管理人报告 | 第5-7页 | 投资策略、运作分析、展望 |
| 投资组合报告 | 第7-10页 | 行业配置、前十大重仓 |

---

## Excel持仓数据处理

```python
import pandas as pd

def process_fund_holdings(excel_path):
    """处理基金持仓Excel"""
    df = pd.read_excel(excel_path)
    
    # 常见的持仓表字段映射
    column_mapping = {
        '股票代码': 'code',
        '股票名称': 'name',
        '持仓数量': 'shares',
        '持仓市值': 'market_value',
        '占净值比': 'weight',
        '行业': 'sector'
    }
    
    # 标准化列名
    for cn, en in column_mapping.items():
        if cn in df.columns:
            df[en] = df[cn]
    
    return df
```

---

## 批量处理下载文件夹

```python
import glob
import os

def scan_downloads_for_fund_reports():
    """扫描下载文件夹中的基金相关文档"""
    downloads = os.path.expanduser("~/Downloads")
    
    results = {
        'pdf_reports': [],  # PDF格式的季报/年报
        'excel_holdings': [],  # Excel持仓数据
        'others': []
    }
    
    # 查找PDF
    for pdf in glob.glob(f"{downloads}/*.pdf"):
        filename = os.path.basename(pdf)
        if any(keyword in filename for keyword in ['基金', '季报', '年报', '招募', 'F']):
            results['pdf_reports'].append(pdf)
    
    # 查找Excel
    for xlsx in glob.glob(f"{downloads}/*.xlsx"):
        results['excel_holdings'].append(xlsx)
    
    return results
```

---

## 与文档处理套件的协作约定

1. **简单提取**：本skill直接嵌入pdfplumber代码（如上述示例）
2. **复杂处理**：若需OCR、复杂表格识别等，显式调用文档处理套件
3. **格式转换**：Excel转CSV等标准化操作，直接嵌入pandas代码
4. **批量任务**：处理>5个文件时，建议调用文档处理套件的批量接口
