"""Coordinate/table extraction. No clinical inference; uncertain records fail closed.

The original PDFs remain the authoritative visual archive. Review records retain
their exact source pages. Use review_page.py to inspect a source page at full size.
"""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SUBJECTS = {
    'BIOCHEMISTRY': 'biochemistry', 'ANATOMY': 'anatomy',
    'MICROBIOLOGY': 'microbiology', 'PHYSIOLOGY': 'physiology',
    'LEGAL MEDICINE AND JURIS': 'legal-medicine', 'PATHOLOGY': 'pathology',
    'PHARMACOLOGY': 'pharmacology', 'SURGERY': 'surgery',
    'INTERNAL MEDICINE': 'internal-medicine',
    'OBSTETRICS-GYNECOLOGY': 'obstetrics-gynecology',
    'PEDIATRICS': 'pediatrics', 'PREVENTIVE MEDICINE': 'preventive-medicine',
}


def clean(text):
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in (text or '').replace('\u00a0', ' ').splitlines()).strip()


def normalized(text):
    return re.sub(r'\s+', '', text).casefold()


def ref(filename, page):
    return {'filename': filename, 'pages': [page], 'answerPages': []}


def add_page(record, filename, page, answer=False):
    source = next((s for s in record['sources'] if s['filename'] == filename), None)
    if source is None:
        source = ref(filename, page) if not answer else {'filename': filename, 'pages': [], 'answerPages': []}
        record['sources'].append(source)
    field = 'answerPages' if answer else 'pages'
    source[field] = sorted(set(source[field] + [page]))


def new_record(subject, number, filename, page, namespace='superexam'):
    return {'id': f'{namespace}-{subject}-{number:04d}', 'subject': subject,
            'originalNumber': number, 'stem': '', 'choices': [], 'correctChoice': None,
            'explanation': '', 'sources': [ref(filename, page)], 'status': 'needs_review',
            'issues': [], '_raw': '', '_namespace': namespace}


def has_visual(page, rectangle):
    rect = fitz.Rect(rectangle)
    # Images and vector drawings inside the cell require visual review. Grid rules
    # are ignored; shapes with area or diagonal/curved segments are not.
    if not hasattr(page, '_review_images'):
        page._review_images = page.get_image_info()
        page._review_drawings = page.get_drawings()
    for image in page._review_images:
        intersection = rect & fitz.Rect(image['bbox'])
        if intersection.get_area() > 20:
            return True
    for drawing in page._review_drawings:
        box = drawing['rect']
        # Visually verified recurring gray diagonal www.topnotchboardprep.com.ph
        # watermark in Avillo. Match its exact color/size/location, not all gray art.
        if ('Karl-Avillo' in page.parent.name and drawing['fill'] == (0.847000002861023,) * 3
                and drawing['color'] is None and box.width < 60 and box.height < 60
                and 690 < box.x0 + box.y0 < 790):
            continue
        if rect.contains(box) and box.width > 3 and box.height > 3:
            if any(item[0] in ('c', 'qu') or (item[0] == 'l' and abs(item[1].x-item[2].x) > 3 and abs(item[1].y-item[2].y) > 3) for item in drawing['items']):
                return True
    return False


def parse_superexam(path, inventory, start=0, end=None):
    doc = fitz.open(path)
    records = {}
    keys = defaultdict(list)
    previous = None
    page_subjects = []
    for i in range(start, len(doc) if end is None else end):
        page = doc[i]
        text = page.get_text()
        match = re.search(r'PREP (.*?) SUPEREXAM', text)
        subject = SUBJECTS.get(match.group(1)) if match else None
        page_subjects.append(subject)
        if not subject:
            inventory['unrecognizedPages'].append({'filename': path.name, 'page': i+1})
            continue
        if previous and previous['subject'] != subject:
            previous = None
        if len(re.findall(r'(?m)^\s*\d{1,3}\s*\n\s*[A-E]\s*$', text)) > 30:
            # Reading order is column by column in the source key tables.
            body = page.get_text(clip=fitz.Rect(20, 58, 590, 889))
            for match in re.finditer(r'(?m)^\s*(\d{1,3})\s*\n([^\n]+)', body):
                number, answer = int(match.group(1)), clean(match.group(2))
                keys[(subject, number)].append((answer, i+1))
            continue
        tables = page.find_tables().tables
        found = False
        for table in tables:
            if table.col_count != 5 or table.bbox[2]-table.bbox[0] < 500:
                continue
            found = True
            for row, cells in zip(table.extract(), table.rows):
                num, question, explanation = [clean(v) for v in row[:3]]
                if 'QUESTION' == question or 'Item' in num:
                    continue
                if re.fullmatch(r'\d{1,3}', num):
                    number = int(num)
                    key = (subject, number)
                    if key in records:
                        records[key]['issues'].append('repeated_source_number')
                        previous = records[key]
                    else:
                        previous = new_record(subject, number, path.name, i+1)
                        records[key] = previous
                elif num:
                    inventory['unparsedRows'].append({'filename': path.name, 'page': i+1, 'number': num})
                    previous = None
                    continue
                if not previous:
                    continue
                if question or explanation:
                    previous['_raw'] = clean(previous['_raw'] + '\n' + question)
                    previous['explanation'] = clean(previous['explanation'] + '\n' + explanation)
                    add_page(previous, path.name, i+1)
                for rect in cells.cells[1:3]:
                    if rect and has_visual(page, rect):
                        previous['issues'].append('source_visual_requires_review')
        if not found:
            inventory['unparsedPages'].append({'filename': path.name, 'page': i+1})
        if (i+1) % 100 == 0:
            print(f'{path.name}: {i+1}/{len(doc)} pages', flush=True)
    for (subject, number), answers in keys.items():
        if (subject, number) not in records:
            records[(subject, number)] = new_record(subject, number, path.name, answers[0][1])
            records[(subject, number)]['issues'].append('missing_question')
        record = records[(subject, number)]
        values = set(a for a, _ in answers)
        if len(values) != 1:
            record['issues'].append('conflicting_answer_keys')
        else:
            record['correctChoice'] = next(iter(values))
        for _, page in answers:
            add_page(record, path.name, page, True)
    return list(records.values()), page_subjects


def parse_section(job):
    path, start, end = job
    inventory = {'unrecognizedPages': [], 'unparsedRows': [], 'unparsedPages': []}
    records, subjects = parse_superexam(path, inventory, start, end)
    return records, subjects, inventory


def parse_merged(path, inventory):
    """Subjects are independent; return worker results in source order.

    Section lengths come from the actual 'Page 1 of N' footer. Never split a
    subject's questions from its keys or split a page continuation across workers.
    """
    doc = fitz.open(path)
    jobs = []
    start = 0
    while start < len(doc):
        match = re.search(r'Page\s+1\s+of\s+(\d+)', doc[start].get_text())
        if not match:
            return parse_superexam(path, inventory)
        end = start + int(match.group(1))
        if end > len(doc):
            return parse_superexam(path, inventory)
        jobs.append((path, start, end))
        start = end
    records, subjects = [], []
    with ProcessPoolExecutor(max_workers=min(4, len(jobs))) as pool:
        for rows, names, issues in pool.map(parse_section, jobs):
            records.extend(rows)
            subjects.extend(names)
            for key, values in issues.items():
                inventory[key].extend(values)
    return records, subjects


def parse_micro(path, inventory):
    doc = fitz.open(path)
    records = {}
    previous_question = None
    previous_answer = None
    for i, page in enumerate(doc):
        is_key = i >= 10
        for left, right in [(29, 294), (318, 583)]:
            tables = page.find_tables(clip=fitz.Rect(left, 58, right, 893)).tables
            for table in tables:
              if table.col_count != (3 if is_key else 2):
                inventory['unparsedRows'].append({'filename': path.name, 'page': i+1, 'reason': 'unexpected_micro_table'})
                continue
              for row, cells in zip(table.extract(), table.rows):
                number_text = clean(row[0])
                if 'Item' in number_text:
                    continue
                if number_text and not re.fullmatch(r'\d{1,3}', number_text):
                    inventory['unparsedRows'].append({'filename': path.name, 'page': i+1, 'number': number_text})
                    continue
                number = int(number_text) if number_text else None
                previous = previous_answer if is_key else previous_question
                if number:
                    if number not in records:
                        records[number] = new_record('microbiology', number, path.name, i+1, 'avillo')
                    previous = records[number]
                    if is_key:
                        previous_answer = previous
                    else:
                        previous_question = previous
                if previous is None:
                    continue
                if is_key:
                    key = clean(row[1])
                    explanation = clean(row[2])
                    if number:
                        previous['correctChoice'] = key
                    previous['explanation'] = clean(previous['explanation'] + '\n' + explanation)
                    add_page(previous, path.name, i+1, True)
                else:
                    raw = clean(row[1])
                    previous['_raw'] = clean(previous['_raw'] + '\n' + raw)
                    add_page(previous, path.name, i+1)
                for rect in cells.cells[1:]:
                    if rect and has_visual(page, rect):
                        previous['issues'].append('source_visual_requires_review')
    return list(records.values())


def validate(record):
    raw = record['_raw']
    prose = re.sub(r'\s+', ' ', raw)
    # Choice markers must occur at line starts. Ambiguous inline/merged markers
    # are retained in raw text and quarantined, never guessed into new options.
    matches = list(re.finditer(r'(?m)^([A-Ea-e])\s*[.)]\s*', raw))
    record['stem'] = clean(raw[:matches[0].start()] if matches else raw)
    record['choices'] = [{'label': m.group(1).upper(), 'text': clean(raw[m.end():matches[j+1].start() if j+1 < len(matches) else len(raw)])} for j, m in enumerate(matches)]
    labels = ''.join(c['label'] for c in record['choices'])
    if labels not in ('ABCD', 'ABCDE') or any(not c['text'] for c in record['choices']):
        record['issues'].append('invalid_or_incomplete_choices')
    if re.search(r'\S[A-E]\.\s', raw) or any(re.search(r'\s[A-E]\.\s', c['text']) for c in record['choices']):
        record['issues'].append('inline_choice_marker_requires_review')
    if not record['correctChoice']:
        record['issues'].append('missing_answer')
    elif record['correctChoice'] not in [c['label'] for c in record['choices']]:
        record['issues'].append('invalid_key')
    if len(record['stem']) < 15:
        record['issues'].append('incomplete_stem')
    if not record['explanation']:
        record['issues'].append('missing_explanation')
    if '\ufffd' in raw + record['explanation'] or '\x00' in raw:
        record['issues'].append('unmapped_symbol')
    if re.search(r'\b(figure|diagram|pictured|shown below|shown above|image below|following graph|following table|table below)\b', prose, re.I):
        record['issues'].append('required_figure_or_table_requires_review')
    if re.search(r'\b(above case|case above|previous case|same patient|preceding case|previous question|patient above|patient described|questions?\s+\d+\s*[-–]|items?\s+\d+\s*[-–]|refer to|based on the case|following questions|following items|next two questions)\b', prose, re.I):
        record['issues'].append('shared_case_requires_review')
    if re.search(r'(should (?:have )?be(?:en)?|typographical|typo|errat(?:a|um)|bonus question|no correct answer)', re.sub(r'\s+', ' ', record['explanation']), re.I):
        record['issues'].append('source_correction_requires_review')
    record['issues'] = sorted(set(record['issues']))
    record['status'] = 'needs_review' if record['issues'] else 'validated'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Re-extract and verify identical published content')
    parser.add_argument('--draft', action='store_true', help='Write .local/extraction.json without publishing')
    args = parser.parse_args()
    inventory = {key: [] for key in ['unrecognizedPages', 'unparsedRows', 'unparsedPages', 'duplicates', 'conflicts', 'files']}
    merged = ROOT / 'raw pdfs/648945218-TopNotch-Merged.pdf'
    records, page_subjects = parse_merged(merged, inventory)
    doc = fitz.open(merged)
    page_hashes = {hashlib.sha256(p.get_text().encode()).hexdigest(): i+1 for i, p in enumerate(doc)}
    for path in sorted((ROOT/'raw pdfs').glob('*.pdf')):
        data = path.read_bytes()
        standalone = fitz.open(path)
        inventory['files'].append({'filename': path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'pages': len(standalone)})
        if path == merged:
            continue
        if 'Karl-Avillo' in path.name:
            records.extend(parse_micro(path, inventory))
            continue
        mapping = {i+1: page_hashes.get(hashlib.sha256(p.get_text().encode()).hexdigest()) for i, p in enumerate(standalone)}
        if all(mapping.values()):
            inverse = {v: k for k, v in mapping.items()}
            for record in records:
                source = record['sources'][0]
                if all(p in inverse for p in source['pages'] + source['answerPages']):
                    record['sources'].append({'filename': path.name, 'pages': [inverse[p] for p in source['pages']], 'answerPages': [inverse[p] for p in source['answerPages']]})
                    inventory['duplicates'].append({'id': record['id'], 'filename': path.name, 'method': 'identical_page_text'})
        else:
            extra, _ = parse_superexam(path, inventory)
            by_id = {r['id']: r for r in records}
            for record in extra:
                existing = by_id.get(record['id'])
                if existing:
                    existing['sources'].extend(record['sources'])
                    if all(normalized(str(existing[k])) == normalized(str(record[k])) for k in ['_raw', 'explanation', 'correctChoice']):
                        inventory['duplicates'].append({'id': record['id'], 'filename': path.name, 'method': 'identical_record'})
                    else:
                        existing['issues'].append('conflicting_source_version')
                        inventory['conflicts'].append({'id': record['id'], 'variant': record})
                else:
                    records.append(record)
    for record in records:
        validate(record)
    # These two groups were checked visually against Avillo page 1. Other
    # ambiguous dependencies stay quarantined rather than inferring case bounds.
    for first, last in [(3, 7), (10, 13)]:
        group = [r for r in records if r['_namespace'] == 'avillo' and first <= r['originalNumber'] <= last]
        anchor = next(r for r in group if r['originalNumber'] == first)
        case = {'id': f'avillo-case-{first}-{last}', 'text': anchor['stem'].split('Which of the following')[0].strip()}
        for record in group:
            record['sharedCase'] = case
            record['issues'] = [issue for issue in record['issues'] if issue != 'shared_case_requires_review']
            record['status'] = 'needs_review' if record['issues'] else 'validated'
        if any(r['issues'] for r in group):
            for record in group:
                record['issues'] = sorted(set(record['issues'] + ['shared_case_member_needs_review']))
                record['status'] = 'needs_review'
    # Exact duplicate content at different original numbers also consolidates.
    fingerprints = {}
    unique = []
    for record in records:
        fingerprint = (record['subject'], normalized(record['_raw']))
        prior = fingerprints.get(fingerprint) if record['_raw'] else None
        if prior and record['correctChoice'] == prior['correctChoice'] and normalized(record['explanation']) == normalized(prior['explanation']):
            prior['sources'].extend(s for s in record['sources'] if s not in prior['sources'])
            inventory['duplicates'].append({'id': record['id'], 'canonicalId': prior['id'], 'method': 'identical_content'})
        else:
            if prior and record['correctChoice'] != prior['correctChoice']:
                record['issues'] = sorted(set(record['issues'] + ['conflicting_duplicate_answer']))
                prior['issues'] = sorted(set(prior['issues'] + ['conflicting_duplicate_answer']))
                record['status'] = prior['status'] = 'needs_review'
            fingerprints[fingerprint] = record
            unique.append(record)
    records = sorted(unique, key=lambda r: r['id'])
    review = [{**r} for r in records if r['status'] == 'needs_review']
    for record in records:
        record.pop('_raw', None)
        record.pop('_namespace', None)
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    version = 'bank-' + hashlib.sha256(payload.encode()).hexdigest()[:16]
    summary = {subject: {'total': sum(r['subject'] == subject for r in records), 'validated': sum(r['subject'] == subject and r['status'] == 'validated' for r in records)} for subject in SUBJECTS.values()}
    report = {'version': version, 'parser': 'PyMuPDF 1.26.7; structural validation, not clinical revalidation', 'summary': summary, 'total': len(records), 'validated': sum(r['status'] == 'validated' for r in records), 'needsReview': len(review), 'issues': dict(sorted(Counter(issue for r in records for issue in r['issues']).items())), **inventory, 'review': review}
    print(json.dumps({k: report[k] for k in ['version', 'summary', 'total', 'validated', 'needsReview', 'issues']}, indent=2), flush=True)
    (ROOT/'.local').mkdir(exist_ok=True)
    (ROOT/'.local/extraction.json').write_text(json.dumps({'records': records, 'report': report}, ensure_ascii=False), encoding='utf-8')
    if args.draft:
        return
    destination = ROOT/'src/data/versions'/version
    files = {}
    for subject in SUBJECTS.values():
        rows = [r for r in records if r['subject'] == subject]
        files[f'{subject}.ts'] = '// Generated by scripts/extract.py. Immutable.\nimport type { Question } from "../../../lib/types";\nexport const questions: Question[] = ' + json.dumps(rows, ensure_ascii=False, indent=2) + ';\n'
    imports = '\n'.join(f'import {{ questions as q{i} }} from "./{subject}";' for i, subject in enumerate(SUBJECTS.values()))
    files['index.ts'] = imports + '\nexport const questions = [' + ', '.join(f'...q{i}' for i in range(12)) + '];\n'
    files['report.json'] = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.check:
        for name, content in files.items():
            if not (destination/name).exists() or (destination/name).read_text(encoding='utf-8') != content:
                raise SystemExit(f'Determinism check failed: {destination/name}')
        print('Deterministic regeneration verified.')
        return
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = destination/name
        if target.exists() and target.read_text(encoding='utf-8') != content:
            raise SystemExit(f'Refusing to change immutable version: {target}')
        target.write_text(content, encoding='utf-8')
    versions = sorted(p.name for p in destination.parent.iterdir() if p.is_dir())
    entry = '// Generated registry. Server use only; never import into client components.\nimport "server-only";\n'
    entry += '\n'.join(f'import {{ questions as v{i} }} from "./versions/{v}";' for i, v in enumerate(versions))
    entry += f'\nexport const BANK_VERSION = "{version}";\n'
    entry += 'export const BANKS = { ' + ', '.join(f'"{v}": v{i}' for i, v in enumerate(versions)) + ' };\n'
    entry += 'export const questionBank = BANKS[BANK_VERSION];\n'
    (ROOT/'src/data/question-bank.ts').write_text(entry)
    (ROOT/'docs').mkdir(exist_ok=True)
    (ROOT/'docs/EXTRACTION_REPORT.md').write_text('# Extraction report\n\nVersion: `' + version + '`\n\n' + f'{report["total"]:,} unique records; {report["validated"]:,} structurally validated; {report["needsReview"]:,} excluded pending review.\n\n' + '| Subject | Records | Available |\n|---|---:|---:|\n' + '\n'.join(f'| {s} | {v["total"]} | {v["validated"]} |' for s, v in summary.items()) + '\n\nFull source inventory, duplicate mappings, conflicts, raw unresolved records and issue counts: [`report.json`](../src/data/versions/' + version + '/report.json).\n\nStructural validation verifies extraction and key pairing; it does not certify the medical currency or correctness of the historical source. Unresolved figures, tables, case dependencies and source corrections remain quarantined. Original PDFs retain the visual source.\n')


if __name__ == '__main__':
    main()
