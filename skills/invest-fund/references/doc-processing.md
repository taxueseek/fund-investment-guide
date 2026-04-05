# 文档处理协作指南

本 skill 在需要处理PDF/Excel等文档时，**声明能力需求**而非点名调用具体 skill。

```yaml
所需能力:
  - PDF_EXTRACTION: 提取基金季报/年报内容
  - EXCEL_ANALYSIS: 分析持仓数据表格

路由: 由 agent-guild 根据当前最优实现自动分配
当前实现: office-skills (PyMuPDF 极速模式)
```

⚡ **性能对比**: PyMuPDF 速度是 pdfplumber 的 **12倍**（0.1s vs 1.4s）

---

## 何时需要文档处理

| 场景 | 处理方式 |
|-----|---------|
| 用户上传PDF基金季报 | 声明 `CAPABILITY: PDF_EXTRACTION` → Guild 路由 |
| 需要批量处理Excel持仓数据 | 声明 `CAPABILITY: EXCEL_ANALYSIS` → Guild 路由 |
| 从下载文件夹读取多个文档 | 声明 `CAPABILITY: PDF_EXTRACTION(batch=true)` |

---

## PDF提取（基金季报专用）⭐ 极速版

**使用 PyMuPDF（速度提升12倍）**

```python
import fitz  # PyMuPDF
import os

def extract_fund_report(pdf_path, max_pages=15):
    """
    提取基金季报/年报核心内容 - 极速版（0.1s/50页）
    通常前15页包含：基金概况、主要财务指标、净值表现、投资组合、管理人报告
    """
    if not os.path.exists(pdf_path):
        return None, "文件不存在"
    
    try:
        doc = fitz.open(pdf_path)
        text = ""
        total_pages = min(len(doc), max_pages)
        
        for i in range(total_pages):
            page = doc[i]
            text += f"\n--- 第{i+1}页 ---\n"
            text += page.get_text()
        
        doc.close()
        return text, f"成功提取{total_pages}页"
    except Exception as e:
        return None, f"提取失败: {str(e)}"

# 使用示例
# text, msg = extract_fund_report("/Users/.../基金季报.pdf")
```

**性能对比**：
- PyMuPDF (新): 0.1s/50页 ⚡
- pdfplumber (旧): 1.4s/50页 🐢
- **速度提升: 12倍**

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
import fitz

def scan_and_extract_fund_reports():
    """扫描并批量处理下载文件夹中的基金季报"""
    downloads = os.path.expanduser("~/Downloads")
    
    results = []
    
    # 查找并处理PDF
    for pdf_path in glob.glob(f"{downloads}/*.pdf"):
        filename = os.path.basename(pdf_path)
        if any(keyword in filename for keyword in ['基金', '季报', '年报', '招募', 'F']):
            # 极速提取前10页
            doc = fitz.open(pdf_path)
            text = ""
            for i in range(min(10, len(doc))):
                text += doc[i].get_text()
            doc.close()
            
            results.append({
                'filename': filename,
                'path': pdf_path,
                'preview': text[:500]
            })
    
    return results
```

---

## 能力声明规范

### 基本用法

```markdown
当用户上传PDF基金季报时：
1. 声明 CAPABILITY: PDF_EXTRACTION
2. 参数: {file_path: path, max_pages: 15}
3. 等待 guild 路由执行并返回提取的文本
4. 基于提取内容进行分析
```

### 批量处理

```markdown
当用户要求批量处理多个PDF时：
1. 声明 CAPABILITY: PDF_EXTRACTION
2. 参数: {batch: true, folder: "~/Downloads", pattern: "*基金*季报*.pdf"}
3. Guild 自动选择支持批量的实现
```

### 降级机制

若当前最优实现（office-skills）不可用，guild 自动降级到备选实现（kimi-pdf），调用方无感知。

---

## 更新日志

### v2.0 (当前)
- **重大升级**: PDF引擎从 pdfplumber 切换到 PyMuPDF
- **性能提升**: 速度提升12倍（1.4s → 0.1s）
- **解决**: 处理PDF卡顿问题

### v1.0
- 基于 pdfplumber 的PDF提取
