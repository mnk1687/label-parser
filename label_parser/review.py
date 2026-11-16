"""Non-blocking review items: PDF text is primary, OCR only raises questions."""
from dataclasses import dataclass, asdict


@dataclass
class ReviewItem:
    """A discrepancy the operator must acknowledge before export, not a silent fix."""
    kind: str
    severity: str          # high / medium
    message: str
    page: int = 0
    row: int = 0
    field: str = ''
    pdf_value: str = ''
    ocr_value: str = ''

    def as_dict(self):
        return asdict(self)


class ReviewRequired(ValueError):
    """Export needs one explicit acknowledgement of the known discrepancies."""

    def __init__(self, items):
        self.items = list(items)
        high = sum(1 for item in self.items if item.severity == 'high')
        super().__init__(f'有 {len(self.items)} 项核对差异待确认（高风险 {high} 项）。')


def review_summary(batch):
    items = list(getattr(batch, 'review_items', []))
    if not items:
        return ''
    high = sum(1 for item in items if item.severity == 'high')
    text = f'{len(items)} 项待确认'
    if high:
        text += f'（高风险 {high} 项）'
    pages = list(getattr(batch, 'ocr_pages', []))
    if pages:
        text += ' · 第 ' + '、'.join(str(page) for page in pages) + ' 页为 OCR'
    return text


KIND_PRIORITY = {
    'ocr_page': 0, 'missing_rows': 1, 'totals': 2, 'missing_row': 3,
    'unreadable': 4, 'identity_conflict': 5, 'ocr_disagreement': 6,
    'continuation': 7, 'txt2_size': 8, 'missing_header': 9, 'ocr_unavailable': 10,
}


def confirmation_text(batch, action):
    items = sorted(getattr(batch, 'review_items', []),
                   key=lambda item: (0 if item.severity == 'high' else 1,
                                     KIND_PRIORITY.get(item.kind, 99)))
    high = sum(1 for item in items if item.severity == 'high')
    lines = [f'· {item.message}' for item in items[:10]]
    if len(items) > 10:
        lines.append(f'· ……另有 {len(items) - 10} 项，详见生成核对报告')
    return (f'准备{action}时发现 {len(items)} 项核对差异（高风险 {high} 项）：\n\n'
            + '\n'.join(lines)
            + '\n\n将继续使用 PDF 文字层/当前解析值，并把差异写入生成核对报告。是否继续？')


def require_exportable(batch, acknowledged=False):
    """Hard errors stop export; review items need one explicit acknowledgement."""
    errors = list(getattr(batch, 'validation_errors', []))
    if errors:
        raise ValueError('ProdSheet 校验未通过，停止导入/导出：\n' + '\n'.join(errors))
    items = list(getattr(batch, 'review_items', []))
    if items and not acknowledged:
        raise ReviewRequired(items)
