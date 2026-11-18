"""Build the Phase 3 Word documents from their Markdown sources.

    Technical_Report/technical_report.md  ->  Technical_Report/Aria_Phase3_Technical_Report.docx
    Design_Plan/design_plan.md            ->  Design_Plan/Design_Plan.docx

Every number in the report is filled in from the captured results in Query_Results/ (the
{{PLACEHOLDER}} markers in the Markdown), so rerunning the pipeline and then this script keeps
the report consistent with the data. Needs python-docx (Embeddings/requirements.txt).

    python Technical_Report/build_report.py
"""
import csv
import datetime as dt
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
Q = ROOT / 'Query_Results'
ACCENT = RGBColor(0x1F, 0x4E, 0x79)


# ---------- figures from Query_Results ----------

def read(name):
    return (Q / name).read_text(encoding='utf-8')


def first(pattern, text, group=1, flags=re.S):
    m = re.search(pattern, text, flags)
    if not m:
        sys.exit(f'build_report: pattern not found: {pattern!r}')
    return m.group(group)


def psql_rows(text, header_start):
    """Rows of the first psql table whose header line starts with header_start."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(header_start):
            rows = []
            for row in lines[i + 2:]:
                if not row.strip() or row.startswith('('):
                    break
                rows.append([c.strip() for c in row.split('|')])
            return rows
    sys.exit(f'build_report: table not found: {header_start!r}')


def md_table(header, rows):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def figures():
    f = {'DATE': dt.date.today().strftime('%B %d, %Y').replace(' 0', ' ')}
    setup0 = read('setup_00_prereqs.txt')
    row = psql_rows(setup0, 'database')[0]
    f['SERVER'], f['PGVECTOR'] = row[1], row[2]

    quality = (ROOT / 'Embeddings' / 'data_quality_report.md').read_text(encoding='utf-8')
    summary = quality.split('## Summary', 1)[1].split('##', 1)[0]
    f['QUALITY_TABLE'] = '\n'.join(l for l in summary.splitlines() if l.startswith('|'))
    tokens = first(r'Embedded text .*?mean ([\d.]+)', quality)
    f['AVG_TOKENS'] = str(round(float(tokens)))
    f['QUALITY_TABLE'] += ('\n\nEmbedded text length in model tokens: '
                           + first(r'in model tokens: (.*?)\n', quality) + '.')

    b1 = read('B1_jsonb_queries.txt')
    plan = first(r'(Seq Scan on products .*?Execution Time: [\d.]+ ms)', b1)
    f['J1_PLAN'] = plan
    f['J1_SEQ_COST'] = first(r'Seq Scan on products\s+\(cost=[\d.]+\.\.([\d.]+)', b1)
    f['J1_GIN_COST'] = first(r'Bitmap Heap Scan on products\s+\(cost=[\d.]+\.\.([\d.]+)', b1)
    size_row = psql_rows(b1, 'products_heap')[0]
    f['PRODUCTS_SIZE'], f['PRODUCTS_PAGES'] = size_row[0], size_row[1]

    with open(Q / 'evaluation.csv', encoding='utf-8') as fh:
        ev = list(csv.DictReader(fh))
    evmd = read('evaluation.md')
    table = evmd.split('| Search |', 1)[1].split('\n\n', 1)[0]
    f['EVAL_TABLE'] = '| Search |' + table
    f['MEAN_P5'] = first(r'\*\*S1-S6\*\*.*?\*\*([\d.]+)\*\*', evmd)
    topic = float(first(r'\*\*S1-S6\*\*.*?\*\*[\d.]+\*\* \| \*\*([\d.]+)\*\*', evmd))
    f['MEAN_TOPIC'] = f'{topic:.0%}'

    c2 = read('C2_filtered_vector_search.txt')
    f['C2_CANDIDATES'] = psql_rows(c2, 'candidates_after_filters')[0][0]
    f['C2_TIME'] = first(r'Execution Time: ([\d.]+) ms', c2)
    f['C2_WITHOUT'] = psql_rows(c2, 'rows_returned_without_iterative_scan')[0][0]
    f['C2_WITH'] = psql_rows(c2, 'rows_returned_with_iterative_scan')[0][0]

    c3 = read('C3_hybrid_search.txt')
    rows = psql_rows(c3, 'method')
    f['HYBRID_TABLE'] = md_table(['Method (search H1)', 'precision@5', 'precision@10'], rows)

    c4 = read('C4_index_comparison.txt')
    f['C4_OVERLAP'] = psql_rows(c4, 'top10_results_in_both')[0][0]
    recall = psql_rows(c4, 'ef_search')
    f['RECALL_LINE'] = ', '.join(f'{r[2]} at ef_search = {r[0]}' for r in recall)
    c4_times = re.findall(r'Execution Time: ([\d.]+) ms', c4)
    sizes = dict((r[0], r[1]) for r in psql_rows(c4, 'index_or_table') ) if 'index_or_table' in c4 else {}
    if not sizes:
        sizes = dict(re.findall(r'^ (\S+)\s+\| (\d+ [kM]B)\s*$', c4, re.M))
    hnsw_build = first(r'CREATE INDEX review_embeddings_hnsw.*?Time: ([\d.]+) ms', read('setup_05_vectors.txt'))

    c5 = read('C5_scale_test.txt')
    c5_times = re.findall(r'Execution Time: ([\d.]+) ms', c5)
    c5_size = psql_rows(c5, 'vectors')[0]
    c5_build = re.findall(r'^Time: ([\d.]+) ms', c5, re.M)
    f['C5_HNSW'], f['C5_EXACT'] = c5_times[0], c5_times[1]
    f['C5_SPEEDUP'] = str(round(float(c5_times[1]) / float(c5_times[0])))
    f['C5_TABLE'], f['C5_INDEX'] = c5_size[1], c5_size[2]
    f['C5_BUILD'] = f'{float(c5_build[1]) / 1000:.1f}'

    d1 = read('D1_combined_query.txt')
    f['D1_TIME'] = first(r'Execution Time: ([\d.]+) ms', d1) if 'Execution Time' in d1 else 'under 1'
    judged = {r['rank']: r['judgement'] for r in ev if r['query_id'] == 'D1'}
    d1rows = psql_rows(d1, 'rank')
    f['D1_TABLE'] = md_table(
        ['#', 'SKU', 'Rating', 'Site, water °C', 'Distance', 'What the diver said (start)', 'Relevant?'],
        [[r[0], r[1], r[5], f'{r[6]}, {r[7]}', r[8], r[9][:85].rstrip() + '…', judged.get(r[0], '')]
         for r in d1rows])

    f['PERF_TABLE'] = md_table(
        ['Measurement (2,390 reviews unless noted)', 'Result'],
        [['S4 top 10, HNSW index scan', f'{c4_times[0]} ms'],
         ['S4 top 10, exact scan (index disabled)', f'{c4_times[1]} ms'],
         ['C2 filtered search (exact, pre-filtered to 107 rows)', f'{f["C2_TIME"]} ms'],
         ['D1 combined query (BitmapAnd + exact sort)', f'{f["D1_TIME"]} ms'],
         ['HNSW build, 2,390 vectors (m=16, ef_construction=64)', f'{float(hnsw_build):.0f} ms'],
         ['HNSW index / embeddings table / tsvector GIN / details GIN / specs GIN',
          ' / '.join(sizes.get(k, '?') for k in ('review_embeddings_hnsw', 'review_embeddings',
                                                  'reviews_tsv_gin', 'reviews_details_gin', 'products_specs_gin'))],
         ['100,000 vectors (C5): HNSW query vs exact parallel scan', f'{f["C5_HNSW"]} ms vs {f["C5_EXACT"]} ms'],
         ['100,000 vectors (C5): HNSW build, index size, table size',
          f'{f["C5_BUILD"]} s, {f["C5_INDEX"]}, {f["C5_TABLE"]}']])
    return f


def fill(text, values):
    def sub(m):
        if m.group(1) not in values:
            sys.exit(f'build_report: no value for {{{{{m.group(1)}}}}}')
        return values[m.group(1)]
    return re.sub(r'\{\{(\w+)\}\}', sub, text)


# ---------- minimal Markdown -> python-docx ----------

INLINE = re.compile(r'(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)')


def add_inline(par, text, size=None, bold=False):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith('**'):
            run = par.add_run(part[2:-2]); run.bold = True
        elif part.startswith('`'):
            run = par.add_run(part[1:-1]); run.font.name = 'Consolas'
            run.font.size = Pt((size or 10.5) - 1)
            run.font.color.rgb = RGBColor(0x8B, 0x1A, 0x1A)
            continue
        elif part.startswith('*'):
            run = par.add_run(part[1:-1]); run.italic = True
        else:
            run = par.add_run(part)
        if bold:
            run.bold = True
        if size:
            run.font.size = Pt(size)


def shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hex_fill)
    tc_pr.append(shd)


def add_table(doc, lines, width_cm):
    rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines]
    header, body = rows[0], [r for r in rows[2:]]
    aligns = ['right' if c.strip().endswith(':') else 'left' for c in lines[1].strip().strip('|').split('|')]
    table = doc.add_table(rows=1 + len(body), cols=len(header))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    size = 8.5 if len(header) > 4 else 9
    for r_i, row in enumerate([header] + body):
        for c_i in range(len(header)):
            cell = table.cell(r_i, c_i)
            par = cell.paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            if aligns[c_i] == 'right':
                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            add_inline(par, row[c_i] if c_i < len(row) else '', size=size, bold=(r_i == 0))
            if r_i == 0:
                shade(cell, 'D9E2F3')
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def convert(md_text, out_path, base_dir):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.59), Cm(27.94)          # US Letter
    for side in ('left_margin', 'right_margin'):
        setattr(sec, side, Cm(2.0))
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    width_cm = 21.59 - 4.0
    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'; normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)
    for name, size in (('Title', 17), ('Heading 1', 13), ('Heading 2', 11.5), ('Heading 3', 10.5)):
        st = doc.styles[name]
        st.font.name = 'Calibri'; st.font.size = Pt(size); st.font.bold = True
        st.font.color.rgb = ACCENT
        st.paragraph_format.space_before = Pt(8 if name != 'Title' else 0)
        st.paragraph_format.space_after = Pt(3)
        st.paragraph_format.keep_with_next = True

    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1; continue
        if s.startswith('```'):
            block = []
            i += 1
            while not lines[i].strip().startswith('```'):
                block.append(lines[i]); i += 1
            i += 1
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Cm(0.3)
            for j, code in enumerate(block):
                run = par.add_run(code); run.font.name = 'Consolas'; run.font.size = Pt(7.5)
                if j < len(block) - 1:
                    run.add_break()
            continue
        if s.startswith('|'):
            block = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                block.append(lines[i]); i += 1
            add_table(doc, block, width_cm)
            continue
        m = re.match(r'!\[(.*?)\]\((.*?)\)', s)
        if m:
            doc.add_picture(str((base_dir / m.group(2)).resolve()), width=Cm(width_cm))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap = doc.add_paragraph()
            add_inline(cap, m.group(1), size=8.5)
            for run in cap.runs:
                run.italic = True
            i += 1; continue
        m = re.match(r'(#{1,3}) (.*)', s)
        if m:
            level = len(m.group(1))
            if level == 1:
                h = doc.add_paragraph(style='Title')
                add_inline(h, m.group(2))
            else:
                h = doc.add_heading(level=level - 1)
                add_inline(h, m.group(2))
            i += 1; continue
        m = re.match(r'( *)[-*] (.*)', line)
        if m:
            depth = len(m.group(1)) // 2
            par = doc.add_paragraph(style='List Bullet' if depth == 0 else 'List Bullet 2')
            par.paragraph_format.space_after = Pt(1)
            add_inline(par, m.group(2))
            i += 1; continue
        if s.startswith('>'):
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Cm(0.8)
            add_inline(par, s.lstrip('> '))
            for run in par.runs:
                run.italic = True
            i += 1; continue
        # plain paragraph: join soft-wrapped lines
        text = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'\s*([-*>|#!]|```)', lines[i]):
            text.append(lines[i].strip()); i += 1
        add_inline(doc.add_paragraph(), ' '.join(text))
    doc.core_properties.author = 'Team Aria'
    doc.save(out_path)
    print(f'wrote {out_path.relative_to(ROOT)}')


def main():
    values = figures()
    report_md = ROOT / 'Technical_Report' / 'technical_report.md'
    convert(fill(report_md.read_text(encoding='utf-8'), values),
            ROOT / 'Technical_Report' / 'Aria_Phase3_Technical_Report.docx', report_md.parent)
    plan_md = ROOT / 'Design_Plan' / 'design_plan.md'
    convert(plan_md.read_text(encoding='utf-8'), ROOT / 'Design_Plan' / 'Design_Plan.docx', plan_md.parent)


if __name__ == '__main__':
    main()
