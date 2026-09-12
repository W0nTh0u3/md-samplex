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

try:
    from .notion_import import (
        discover_export_files,
        has_multiple_indicator,
        parse_export,
        parse_multiple_answer,
        subject_slug,
    )
except ImportError:  # Running the canonical script directly from scripts/.
    from notion_import import (
        discover_export_files,
        has_multiple_indicator,
        parse_export,
        parse_multiple_answer,
        subject_slug,
    )

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


def load_source_manifest(path):
    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise SystemExit(f'Source manifest not found: {manifest_path}') from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get('sources'), list):
        raise SystemExit(f'Invalid source manifest: {manifest_path}')
    enabled = []
    seen = set()
    for source in manifest['sources']:
        if not isinstance(source, dict) or not source.get('path'):
            raise SystemExit(f'Invalid source entry in {manifest_path}')
        if not source.get('enabled', False):
            continue
        kind = source.get('kind')
        if kind not in {'pdf', 'notion'}:
            raise SystemExit(f'Unsupported source kind {kind!r} in {manifest_path}')
        path_value = Path(source['path'])
        resolved = path_value if path_value.is_absolute() else ROOT / path_value
        if not resolved.exists():
            raise SystemExit(f'Enabled source is missing: {resolved}')
        identity = str(resolved.resolve())
        if identity in seen:
            raise SystemExit(f'Duplicate enabled source: {resolved}')
        seen.add(identity)
        enabled.append({**source, '_path': resolved})
    canonical = [
        source for source in enabled
        if source['kind'] == 'pdf' and source.get('role') == 'canonical'
    ]
    if len(canonical) != 1:
        raise SystemExit('The source manifest must enable exactly one canonical PDF.')
    return manifest, enabled, canonical[0]


def notion_file_value(source, path, key):
    """Resolve an optional per-file manifest value for a Notion export."""

    values = source.get(key)
    if not isinstance(values, dict):
        return None
    root = source['_path']
    relative = path.relative_to(root).as_posix() if root.is_dir() else path.name
    return values.get(relative) or values.get(path.name)


def notion_subject(source, path):
    configured = notion_file_value(source, path, 'subjects') or source.get('subject')
    if configured:
        resolved = subject_slug(str(configured))
        if resolved not in SUBJECTS.values():
            raise SystemExit(
                f'Notion source has an unknown subject {configured!r}: {path}. '
                'Use one of the canonical subject IDs in scripts/extract.py.'
            )
        return resolved
    # A subject-named file is safe to infer; arbitrary filenames are not. The
    # manifest remains the authority when a Notion export uses generated names.
    resolved = subject_slug(path.stem)
    if resolved in SUBJECTS.values():
        return resolved
    raise SystemExit(
        f'Enabled Notion source needs a subject for {path}. Add "subject" '
        'for one file or a "subjects" map keyed by the relative export filename.'
    )


def parse_public_snapshot(snapshot, review_only):
    """Load the public adapter lazily to avoid its validation import cycle."""

    try:
        from .notion_public_import import parse_snapshot
    except ImportError:  # Running the canonical script directly from scripts/.
        from notion_public_import import parse_snapshot
    return parse_snapshot(snapshot, review_only=review_only)


def _manifest_asset_path(value):
    """Resolve a manifest asset to a repository-local file."""
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if value.startswith('/assets/'):
        return ROOT / 'public' / value.lstrip('/')
    if path.is_absolute():
        return path
    return ROOT / value


def _source_locator(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        return None
    if isinstance(value.get('locator'), str) and value['locator'].strip():
        return value['locator'].strip()
    if isinstance(value.get('url'), str) and value['url'].strip():
        return value['url'].strip()
    filename = value.get('filename')
    pages = value.get('pages')
    if isinstance(filename, str) and isinstance(pages, list) and pages:
        return f'{filename} pages {", ".join(str(page) for page in pages)}'
    return None


def load_visual_manifest(path):
    """Load and verify the opt-in local visual dependency manifest.

    Invalid entries are retained as manifest errors so a dependent question
    can be quarantined and the report can explain why. No network path or
    unhashable local file can become a rendered asset.
    """
    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.exists():
        return {
            'path': str(manifest_path),
            'assets': {},
            'questions': {},
            'sharedCases': {},
            'errors': [],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid visual manifest: {manifest_path}: {error}') from error
    if not isinstance(manifest, dict):
        raise SystemExit(f'Invalid visual manifest: {manifest_path}')

    errors = []
    assets = {}
    raw_assets = manifest.get('assets', [])
    if isinstance(raw_assets, dict):
        raw_assets = [{**value, 'id': key} for key, value in raw_assets.items() if isinstance(value, dict)]
    if not isinstance(raw_assets, list):
        raise SystemExit(f'Visual manifest assets must be a list or map: {manifest_path}')
    for raw in raw_assets:
        if not isinstance(raw, dict):
            errors.append({'reason': 'invalid_asset_entry', 'entry': raw})
            continue
        asset_id = raw.get('id')
        asset_path = raw.get('path')
        expected_hash = raw.get('sha256')
        kind = raw.get('kind')
        alt = raw.get('alt')
        visibility = raw.get('visibility', 'question')
        error_reasons = []
        if not isinstance(asset_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', asset_id):
            error_reasons.append('invalid_asset_id')
        if not isinstance(asset_path, str) or not asset_path.startswith('/assets/') or '..' in asset_path or '\\' in asset_path:
            error_reasons.append('asset_path_must_be_local')
        if not isinstance(expected_hash, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_hash):
            error_reasons.append('invalid_asset_hash')
        if kind not in {'image', 'table', 'diagram'}:
            error_reasons.append('invalid_visual_kind')
        if not isinstance(alt, str) or not alt.strip():
            error_reasons.append('missing_visual_alt')
        if visibility not in {'question', 'feedback'}:
            error_reasons.append('invalid_visual_visibility')
        disk_path = _manifest_asset_path(raw.get('localPath') or asset_path)
        actual_hash = None
        if disk_path is None or not disk_path.is_file():
            error_reasons.append('missing_local_asset')
        else:
            actual_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()
            if actual_hash.casefold() != str(expected_hash).casefold():
                error_reasons.append('asset_hash_mismatch')
        source_locator = _source_locator(raw.get('source') or raw.get('sourceLocator'))
        if not source_locator:
            error_reasons.append('missing_visual_source_locator')
        answer_marked = bool(
            raw.get('answerMarked') or raw.get('annotated') or raw.get('containsAnswerMark')
        )
        if answer_marked:
            visibility = 'feedback'
        if error_reasons:
            errors.append({'id': asset_id, 'reason': error_reasons, 'path': asset_path})
        if isinstance(asset_id, str) and asset_id not in assets:
            assets[asset_id] = {
                'id': asset_id,
                'path': asset_path,
                'sha256': str(expected_hash).lower(),
                'kind': kind,
                'alt': alt.strip() if isinstance(alt, str) else '',
                'caption': raw.get('caption') if isinstance(raw.get('caption'), str) else None,
                'visibility': visibility,
                '_valid': not error_reasons,
                '_sourceLocator': source_locator,
                '_answerMarked': answer_marked,
            }
        elif isinstance(asset_id, str):
            assets[asset_id]['_valid'] = False
            errors.append({'id': asset_id, 'reason': ['duplicate_asset_id']})

    def entries(value, key_name):
        if isinstance(value, dict):
            return [
                {**entry, key_name: key}
                for key, entry in value.items()
                if isinstance(entry, dict)
            ]
        return value if isinstance(value, list) else []

    questions = {}
    duplicate_questions = set()
    for entry in entries(manifest.get('questions', []), 'questionId') + entries(manifest.get('dependencies', []), 'questionId'):
        question_id = entry.get('questionId') or entry.get('id')
        if not isinstance(question_id, str) or not question_id:
            errors.append({'reason': 'visual_dependency_missing_question_id', 'entry': entry})
            continue
        if question_id in questions:
            errors.append({'id': question_id, 'reason': ['duplicate_visual_dependency']})
            duplicate_questions.add(question_id)
            continue
        questions[question_id] = entry
    for question_id in duplicate_questions:
        questions.pop(question_id, None)
    shared_cases = {}
    duplicate_shared_cases = set()
    for entry in entries(manifest.get('sharedCases', []), 'sharedCaseId'):
        case_id = entry.get('sharedCaseId') or entry.get('id')
        if isinstance(case_id, str) and case_id:
            if case_id in shared_cases:
                errors.append({'id': case_id, 'reason': ['duplicate_visual_shared_case']})
                duplicate_shared_cases.add(case_id)
                continue
            shared_cases[case_id] = entry
        else:
            errors.append({'reason': 'visual_shared_case_missing_id', 'entry': entry})
    for case_id in duplicate_shared_cases:
        shared_cases.pop(case_id, None)
    return {
        'path': str(manifest_path),
        'assets': assets,
        'questions': questions,
        'sharedCases': shared_cases,
        'errors': errors,
    }


def _manifest_asset_ids(entry):
    values = []
    for key in ('visualIds', 'assetIds', 'requiredVisualIds', 'requiredAssetIds', 'visuals'):
        value = entry.get(key)
        if isinstance(value, list):
            values.extend(value)
    ids = []
    for value in values:
        asset_id = value if isinstance(value, str) else value.get('id') if isinstance(value, dict) else None
        if isinstance(asset_id, str) and asset_id and asset_id not in ids:
            ids.append(asset_id)
    return ids


def _manifest_required_asset_ids(entry, fallback):
    for key in ('requiredVisualIds', 'requiredAssetIds'):
        if key in entry:
            value = entry.get(key)
            if not isinstance(value, list):
                return []
            return _manifest_value_ids(value)
    return list(fallback)


def _manifest_value_ids(values):
    ids = []
    for value in values:
        asset_id = value if isinstance(value, str) else value.get('id') if isinstance(value, dict) else None
        if isinstance(asset_id, str) and asset_id and asset_id not in ids:
            ids.append(asset_id)
    return ids


def _visual_ref(asset):
    return {
        **{
            key: asset[key]
            for key in ('id', 'path', 'sha256', 'kind', 'alt', 'caption', 'visibility')
            if asset.get(key) is not None
        },
        **({'sourceLocator': asset['_sourceLocator']} if asset.get('_sourceLocator') else {}),
    }


def apply_visual_manifest(records, manifest, inventory):
    """Attach only verified visuals and verified answer corrections."""
    if not manifest['assets'] and not manifest['questions'] and not manifest['sharedCases'] and not manifest['errors']:
        return
    visual_report = {
        'manifest': manifest['path'],
        'assets': [
            {key: value for key, value in asset.items() if not key.startswith('_')}
            for asset in manifest['assets'].values()
        ],
        'dependencies': [],
        'errors': list(manifest['errors']),
    }
    for record in records:
        entry = manifest['questions'].get(record['id'])
        if not entry:
            continue
        visual_ids = _manifest_asset_ids(entry)
        required_ids = _manifest_required_asset_ids(entry, visual_ids)
        asset_ids = list(dict.fromkeys([*visual_ids, *required_ids]))
        attached = []
        invalid = []
        for asset_id in asset_ids:
            asset = manifest['assets'].get(asset_id)
            if not asset or not asset.get('_valid'):
                invalid.append({'id': asset_id, 'reason': 'unverified_visual_asset'})
                continue
            attached.append(_visual_ref(asset))
        if attached:
            record['visuals'] = attached
        verified = entry.get('verified') is True or entry.get('answerKeyVerified') is True
        explicit_multiple = entry.get('answerMode') == 'multiple'
        answer_issues = {
            'invalid_answer_mode',
            'invalid_key',
            'invalid_single_key',
            'invalid_multiple_key',
            'malformed_multiple_answer_key',
            'missing_answer',
            'mismatched_answer_mode',
            'multiple_response_requires_review',
        }
        if entry.get('answerMode') in {'single', 'multiple'} and verified:
            record['answerMode'] = entry['answerMode']
            if entry['answerMode'] == 'multiple':
                key = entry.get('correctChoices')
                valid_key = (
                    isinstance(key, list)
                    and bool(key)
                    and all(isinstance(label, str) and re.fullmatch(r'[A-E]', label) for label in key)
                    and len(set(key)) == len(key)
                )
                if valid_key:
                    record['correctChoice'] = None
                    record['correctChoices'] = key
                    record['_multiple_explicit'] = explicit_multiple
                    record['issues'] = [
                        issue for issue in record['issues']
                        if issue not in answer_issues
                    ]
                else:
                    record['issues'].append('invalid_multiple_key')
            elif isinstance(entry.get('correctChoice'), str) and re.fullmatch(r'[A-E]', entry['correctChoice']):
                record['correctChoice'] = entry['correctChoice']
                record.pop('correctChoices', None)
                record['issues'] = [
                    issue for issue in record['issues']
                    if issue not in answer_issues
                ]
            else:
                record['issues'].append('invalid_single_key')
        elif entry.get('answerMode') == 'multiple':
            record['issues'].append('multiple_response_requires_review')
        question_visible = [
            asset for asset in attached
            if asset['id'] in required_ids and asset['visibility'] == 'question'
        ]
        required_visuals_verified = (
            bool(required_ids)
            and len(question_visible) == len(required_ids)
        )
        if invalid or (asset_ids and not verified) or (
            required_ids and not required_visuals_verified
        ):
            record['issues'].append('visual_dependency_requires_review')
        if any(
            manifest['assets'].get(asset_id, {}).get('_answerMarked')
            for asset_id in required_ids
        ):
            record['issues'].append('answer_marked_visual_feedback_only')
        if any(issue in record['issues'] for issue in ('required_figure_or_table_requires_review', 'source_visual_requires_review')):
            if verified and required_visuals_verified and not invalid and not any(
                manifest['assets'].get(asset_id, {}).get('_answerMarked') for asset_id in required_ids
            ):
                record['issues'] = [
                    issue for issue in record['issues']
                    if issue not in {'required_figure_or_table_requires_review', 'source_visual_requires_review'}
                ]
            else:
                record['issues'].append('visual_dependency_requires_review')
        visual_report['dependencies'].append({
            'questionId': record['id'],
            'assetIds': asset_ids,
            'requiredAssetIds': required_ids,
            'verified': verified,
            'attached': [asset['id'] for asset in attached],
            'invalid': invalid,
        })

    for record in records:
        case = record.get('sharedCase')
        if not case:
            continue
        entry = manifest['sharedCases'].get(case['id'])
        if not entry:
            continue
        if isinstance(entry.get('text'), str) and entry['text'].strip():
            case['text'] = clean(entry['text'])
        visual_ids = _manifest_asset_ids(entry)
        required_ids = _manifest_required_asset_ids(entry, visual_ids)
        asset_ids = list(dict.fromkeys([*visual_ids, *required_ids]))
        attached = []
        invalid = []
        for asset_id in asset_ids:
            asset = manifest['assets'].get(asset_id)
            if not asset or not asset.get('_valid'):
                invalid.append(asset_id)
            else:
                attached.append(_visual_ref(asset))
        if attached:
            case['visuals'] = attached
        verified = entry.get('verified') is True or entry.get('visualVerified') is True
        question_visible = [
            asset
            for asset in attached
            if asset['id'] in required_ids and asset['visibility'] == 'question'
        ]
        required_visuals_verified = (
            not required_ids or len(question_visible) == len(required_ids)
        )
        answer_marked_required = any(
            manifest['assets'].get(asset_id, {}).get('_answerMarked')
            for asset_id in required_ids
        )
        if invalid or (asset_ids and not verified) or not required_visuals_verified:
            record['issues'].append('shared_case_visual_dependency_requires_review')
        else:
            record['issues'] = [
                issue
                for issue in record['issues']
                if issue != 'shared_case_visual_dependency_requires_review'
            ]
        if answer_marked_required:
            record['issues'].append('answer_marked_visual_feedback_only')
        visual_report['dependencies'].append({
            'questionId': record['id'],
            'sharedCaseId': case['id'],
            'assetIds': asset_ids,
            'requiredAssetIds': required_ids,
            'verified': verified,
            'attached': [asset['id'] for asset in attached],
            'invalid': invalid,
        })
    inventory['visuals'] = visual_report


def clean(text):
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in str(text or '').replace('\u00a0', ' ').splitlines()).strip()


def normalized(text):
    return re.sub(r'\s+', '', str(text)).casefold()


def label_set(value):
    """Parse a complete, delimiter-separated A-E label set."""
    match = re.fullmatch(
        r'\s*[A-Ea-e](?:\s*(?:,|/|and|&|\+)\s*[A-Ea-e])+\s*',
        value or '',
    )
    if not match:
        return None
    labels = [label.upper() for label in re.findall(r'[A-Ea-e]', value)]
    if len(labels) < 2 or len(set(labels)) != len(labels):
        return None
    return labels


def parse_key_value(value, stem=''):
    """Return a key only when its mode and label set are explicit."""
    text = clean(value).upper()
    explicit_multiple = parse_multiple_answer(value)
    if explicit_multiple:
        return {'answerMode': 'multiple', 'correctChoices': explicit_multiple,
                'correctChoice': None, '_multiple_explicit': True}
    if has_multiple_indicator(stem):
        labels = label_set(text)
        if labels:
            return {'answerMode': 'multiple', 'correctChoices': labels,
                    'correctChoice': None, '_multiple_explicit': True}
        if len(re.findall(r'[A-E]', text)) > 1:
            return {'answerMode': 'multiple', 'correctChoices': [],
                    'correctChoice': None, '_multiple_explicit': True,
                    '_malformed_multiple': True}
    single = re.fullmatch(r'(?:OPTION\s*)?([A-E])', text)
    if single:
        return {'answerMode': 'single', 'correctChoice': single.group(1)}
    return None


def answer_signature(record):
    mode = record.get('answerMode') or 'single'
    if mode == 'multiple':
        return mode, tuple(sorted(record.get('correctChoices') or []))
    return mode, (record.get('correctChoice'),)


def parsed_key_signature(parsed, raw):
    if not parsed:
        return ('raw', normalized(str(raw)))
    if parsed.get('answerMode') == 'multiple':
        return (
            'multiple',
            tuple(sorted(parsed.get('correctChoices') or [])),
            bool(parsed.get('_malformed_multiple')),
        )
    return ('single', parsed.get('correctChoice'))


def rationale_signature(record):
    return {
        label: normalized(str(text))
        for label, text in (record.get('choiceRationales') or {}).items()
    }


def visual_signature(record):
    def signature_item(scope, visual):
        return (
            scope,
            visual.get('id'),
            visual.get('path'),
            visual.get('sha256'),
            visual.get('kind'),
            visual.get('alt'),
            visual.get('caption'),
            visual.get('visibility'),
            visual.get('sourceLocator'),
        )

    signature = {
        signature_item('question', visual)
        for visual in (record.get('visuals') or [])
        if isinstance(visual, dict)
    }
    shared_case = record.get('sharedCase') or {}
    signature.update(
        signature_item('shared-case', visual)
        for visual in (shared_case.get('visuals') or [])
        if isinstance(visual, dict)
    )
    return signature


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
                keys[(subject, number)].append((parse_key_value(answer), answer, i + 1))
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
            records[(subject, number)] = new_record(subject, number, path.name, answers[0][2])
            records[(subject, number)]['issues'].append('missing_question')
        record = records[(subject, number)]
        parsed_answers = [
            (parse_key_value(raw, record.get('stem', '')) or parsed, raw, page)
            for parsed, raw, page in answers
        ]
        signatures = {
            parsed_key_signature(parsed, raw)
            for parsed, raw, _ in parsed_answers
        }
        if len(signatures) != 1:
            record['issues'].append('conflicting_answer_keys')
        else:
            parsed = parsed_answers[0][0]
            if parsed is None:
                record['issues'].append('invalid_key')
            elif parsed.get('_malformed_multiple'):
                record.update({
                    'answerMode': 'multiple',
                    'correctChoice': None,
                    'correctChoices': [],
                    '_multiple_explicit': True,
                })
                record['issues'].append('malformed_multiple_answer_key')
            elif parsed.get('answerMode') == 'multiple':
                record.update({
                    'answerMode': 'multiple',
                    'correctChoice': None,
                    'correctChoices': parsed['correctChoices'],
                    '_multiple_explicit': True,
                })
            else:
                record['correctChoice'] = parsed['correctChoice']
        for _, _, page in parsed_answers:
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
                        parsed = parse_key_value(key, previous.get('_raw', ''))
                        if parsed is None:
                            previous['issues'].append('invalid_key')
                        elif parsed.get('answerMode') == 'multiple':
                            previous.update({
                                'answerMode': 'multiple',
                                'correctChoice': None,
                                'correctChoices': parsed['correctChoices'],
                                '_multiple_explicit': True,
                            })
                        else:
                            previous['correctChoice'] = parsed['correctChoice']
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


def validate_answer_contract(record, labels):
    """Validate answer mode and keyed labels without inferring a key."""
    mode = record.get('answerMode', 'single')
    available_labels = set(labels)
    if mode not in {'single', 'multiple'}:
        record['issues'].append('invalid_answer_mode')
        return
    if mode == 'multiple':
        correct = record.get('correctChoices')
        if record.get('correctChoice') is not None:
            record['issues'].append('mismatched_answer_mode')
        if (
            not isinstance(correct, list)
            or not correct
            or not all(isinstance(label, str) for label in correct)
            or len(set(correct)) != len(correct)
            or any(label not in available_labels for label in correct)
        ):
            record['issues'].append('invalid_multiple_key')
        if not record.get('_multiple_explicit'):
            record['issues'].append('multiple_response_requires_review')
    else:
        if record.get('correctChoices') is not None:
            record['issues'].append('mismatched_answer_mode')
        if not record.get('correctChoice'):
            record['issues'].append('missing_answer')
        elif record['correctChoice'] not in available_labels:
            record['issues'].append('invalid_key')


def validate_notion(record):
    """Validate the structured Notion representation without guessing."""
    record['stem'] = clean(record.get('stem', ''))
    record['explanation'] = clean(record.get('explanation', ''))
    record['choiceRationales'] = {
        label: clean(text)
        for label, text in (record.get('choiceRationales') or {}).items()
        if clean(text)
    }
    labels = ''.join(choice.get('label', '') for choice in record.get('choices', []))
    if labels not in ('ABCD', 'ABCDE') or any(not clean(choice.get('text')) for choice in record['choices']):
        record['issues'].append('invalid_or_incomplete_choices')
    validate_answer_contract(record, labels)
    if len(record['stem']) < 15:
        record['issues'].append('incomplete_stem')
    rationale_labels = set(record['choiceRationales'])
    if rationale_labels and rationale_labels != set(labels):
        record['issues'].append('incomplete_choice_rationales')
    if not record['explanation']:
        keyed = record.get('correctChoices', []) if record.get('answerMode') == 'multiple' else [record.get('correctChoice')]
        fallback = ' '.join(record['choiceRationales'].get(label, '') for label in keyed if label)
        if fallback:
            record['explanation'] = clean(fallback)
    if not record['choiceRationales']:
        record.pop('choiceRationales', None)
    if not record['explanation']:
        record['issues'].append('missing_explanation')
    prose = re.sub(r'\s+', ' ', record['stem'])
    if has_multiple_indicator(prose) and record.get('answerMode', 'single') != 'multiple':
        record['issues'].append('multiple_response_requires_review')
    if re.search(r'\b(match(?:ing)?|pair the|column [a-z]|type matching)\b', prose, re.I):
        record['issues'].append('matching_requires_review')
    if re.search(r'\b(fill[ -]?in(?: the blank)?|complete the sentence)\b', prose, re.I):
        record['issues'].append('fill_in_requires_review')
    has_question_visual = any(
        visual.get('visibility') == 'question'
        for visual in (record.get('visuals') or [])
        if isinstance(visual, dict)
    )
    if any(re.search(r'\b(figure|diagram|pictured|shown below|shown above|image below|following graph|following table|table below)\b', part, re.I)
           for part in [prose, record['explanation']]) and not has_question_visual:
        record['issues'].append('required_figure_or_table_requires_review')
    if 'source_visual_requires_review' in record['issues'] and not has_question_visual:
        record['issues'].append('source_visual_requires_review')
    if re.search(r'\b(above case|case above|previous case|same patient|preceding case|previous question|patient above|refer to|based on the case|following questions|following items|next two questions)\b', prose, re.I):
        record['issues'].append('shared_case_requires_review')
    if '\ufffd' in record['stem'] + record['explanation'] or '\x00' in record['stem']:
        record['issues'].append('unmapped_symbol')
    record['issues'] = sorted(set(record['issues']))
    record['status'] = 'needs_review' if record['issues'] else 'validated'


def validate(record):
    if record.get('_source_kind') == 'notion':
        validate_notion(record)
        return
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
    validate_answer_contract(record, [c['label'] for c in record['choices']])
    if len(record['stem']) < 15:
        record['issues'].append('incomplete_stem')
    if not record['explanation']:
        record['issues'].append('missing_explanation')
    if has_multiple_indicator(prose) and record.get('answerMode', 'single') != 'multiple':
        record['issues'].append('multiple_response_requires_review')
    if '\ufffd' in raw + record['explanation'] or '\x00' in raw:
        record['issues'].append('unmapped_symbol')
    has_question_visual = any(
        visual.get('visibility') == 'question'
        for visual in (record.get('visuals') or [])
        if isinstance(visual, dict)
    )
    if re.search(r'\b(figure|diagram|pictured|shown below|shown above|image below|following graph|following table|table below)\b', prose, re.I) and not has_question_visual:
        record['issues'].append('required_figure_or_table_requires_review')
    if 'source_visual_requires_review' in record['issues'] and not has_question_visual:
        record['issues'].append('source_visual_requires_review')
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
    parser.add_argument('--manifest', default='scripts/source-manifest.json', help='Repository-relative source manifest')
    parser.add_argument('--visual-manifest', default='scripts/visual-manifest.json', help='Opt-in verified visual/key manifest')
    args = parser.parse_args()
    _, enabled_sources, canonical_source = load_source_manifest(args.manifest)
    visual_manifest = load_visual_manifest(args.visual_manifest)
    inventory = {key: [] for key in ['unrecognizedPages', 'unparsedRows', 'unparsedPages', 'duplicates', 'conflicts', 'files']}
    merged = canonical_source['_path']
    records, page_subjects = parse_merged(merged, inventory)
    doc = fitz.open(merged)
    page_hashes = {hashlib.sha256(p.get_text().encode()).hexdigest(): i+1 for i, p in enumerate(doc)}
    pdf_sources = sorted(
        (source for source in enabled_sources if source['kind'] == 'pdf'),
        key=lambda source: source['_path'].name,
    )
    for source in pdf_sources:
        path = source['_path']
        data = path.read_bytes()
        standalone = fitz.open(path)
        file_info = {'filename': path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'pages': len(standalone)}
        inventory['files'].append(file_info)
        if path == merged:
            continue
        if source.get('parser') == 'ocr-sample':
            inventory.setdefault('ocr', []).append({
                'filename': path.name,
                'sha256': file_info['sha256'],
                'pages': source.get('ocr', {}).get('pages', []),
                'configuration': source.get('ocr', {}),
                'reviewStatus': source.get('reviewStatus', 'needs_review'),
            })
            continue
        if source.get('parser') == 'microbiology' or 'Karl-Avillo' in path.name:
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
                    same_text = all(
                        normalized(str(existing[k])) == normalized(str(record[k]))
                        for k in ['_raw', 'explanation']
                    )
                    same_answer = answer_signature(existing) == answer_signature(record)
                    same_rationales = rationale_signature(existing) == rationale_signature(record)
                    same_visuals = (
                        not visual_signature(existing)
                        or not visual_signature(record)
                        or visual_signature(existing) == visual_signature(record)
                    )
                    if same_text and same_answer and same_rationales and same_visuals:
                        if not existing.get('visuals') and record.get('visuals'):
                            existing['visuals'] = record['visuals']
                        if (
                            existing.get('sharedCase')
                            and record.get('sharedCase')
                            and not existing['sharedCase'].get('visuals')
                            and record['sharedCase'].get('visuals')
                        ):
                            existing['sharedCase']['visuals'] = record['sharedCase']['visuals']
                        inventory['duplicates'].append({'id': record['id'], 'filename': path.name, 'method': 'identical_record'})
                    else:
                        existing['issues'].append('conflicting_source_version')
                        record['issues'].append('conflicting_source_version')
                        inventory['conflicts'].append({'id': record['id'], 'variant': {**record}})
                        records.append(record)
                else:
                    records.append(record)
    for source in sorted(
        (source for source in enabled_sources if source['kind'] == 'notion'),
        key=lambda item: item['_path'].name,
    ):
        source_path = source['_path']
        if source.get('parser') == 'notion-public-snapshot':
            try:
                snapshot = json.loads(source_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as error:
                raise SystemExit(f'Invalid public Notion snapshot: {source_path}: {error}') from error
            notion_records, notion_report = parse_public_snapshot(
                snapshot,
                review_only=not source.get('answerHighlightsVerified', False),
            )
            records.extend(notion_records)
            data = source_path.read_bytes()
            file_hash = hashlib.sha256(data).hexdigest()
            inventory['files'].append({
                'filename': source_path.name,
                'sha256': file_hash,
                'pages': len(snapshot.get('pages', [])),
                'kind': 'notion',
            })
            inventory.setdefault('notion', []).append({
                **notion_report,
                'filename': source_path.name,
                'sha256': file_hash,
                'reviewStatus': source.get('reviewStatus', notion_report['reviewStatus']),
            })
            continue
        try:
            notion_files = discover_export_files(source_path)
        except (FileNotFoundError, ValueError) as error:
            raise SystemExit(str(error)) from error
        for notion_file in notion_files:
            subject = notion_subject(source, notion_file)
            relative_name = (
                notion_file.relative_to(source_path).as_posix()
                if source_path.is_dir()
                else notion_file.name
            )
            data = notion_file.read_bytes()
            notion_records, notion_report = parse_export(
                notion_file,
                subject,
                notion_file_value(source, notion_file, 'urls') or source.get('canonicalUrl'),
                notion_file_value(source, notion_file, 'titles') or source.get('title'),
                source_filename=relative_name,
            )
            records.extend(notion_records)
            file_hash = hashlib.sha256(data).hexdigest()
            inventory['files'].append({
                'filename': relative_name,
                'sha256': file_hash,
                'pages': 0,
                'kind': 'notion',
            })
            inventory.setdefault('notion', []).append({
                **notion_report,
                'subject': subject,
                'sha256': file_hash,
                'reviewStatus': source.get('reviewStatus', notion_report['reviewStatus']),
            })
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
    apply_visual_manifest(records, visual_manifest, inventory)
    # Manifest entries may satisfy a previously quarantined visual dependency
    # or supply a verified multiple-response key. Re-run structural validation
    # after applying those explicit facts.
    for record in records:
        validate(record)
    # Exact normalized question content at different source locations also
    # consolidates. A Notion export may add per-choice rationales to an older
    # PDF question, so explanation text is supplemental in that case. A
    # conflicting key or conflicting rationale is retained as review data.
    fingerprints = {}
    unique = []
    for record in records:
        fingerprint = (record['subject'], normalized(record['_raw']))
        prior = fingerprints.get(fingerprint) if record['_raw'] else None
        notion_variant = prior and (prior.get('_source_kind') == 'notion' or record.get('_source_kind') == 'notion')
        same_explanation = prior and normalized(record['explanation']) == normalized(prior['explanation'])
        explanation_compatible = prior and (
            same_explanation
            or not record.get('explanation')
            or not prior.get('explanation')
        )
        prior_rationales = rationale_signature(prior) if prior else {}
        current_rationales = rationale_signature(record)
        rationale_conflict = prior and any(
            label in prior_rationales and prior_rationales[label] != text
            for label, text in current_rationales.items()
        )
        prior_visuals = visual_signature(prior) if prior else set()
        current_visuals = visual_signature(record)
        visual_conflict = prior and prior_visuals and current_visuals and prior_visuals != current_visuals
        same_answer = prior and answer_signature(record) == answer_signature(prior)
        if prior and same_answer and explanation_compatible and not rationale_conflict and not visual_conflict:
            if notion_variant and record['status'] != 'validated':
                # Keep an unresolved Notion variant visible in the review
                # report. Never let partial rationales or an uncertain key
                # enrich an otherwise eligible canonical question.
                record['issues'] = sorted(set(record['issues'] + ['duplicate_content_requires_review']))
                record['status'] = 'needs_review'
                unique.append(record)
                inventory['conflicts'].append({'id': record['id'], 'canonicalId': prior['id'], 'variant': {**record}})
                continue
            prior_rationales_raw = prior.setdefault('choiceRationales', {})
            for label, text in (record.get('choiceRationales') or {}).items():
                prior_rationales_raw.setdefault(label, text)
            if not prior.get('visuals') and record.get('visuals'):
                prior['visuals'] = record['visuals']
            if (
                prior.get('sharedCase')
                and record.get('sharedCase')
                and not prior['sharedCase'].get('visuals')
                and record['sharedCase'].get('visuals')
            ):
                prior['sharedCase']['visuals'] = record['sharedCase']['visuals']
            if not prior.get('explanation') and record.get('explanation'):
                prior['explanation'] = record['explanation']
            if not prior_rationales:
                prior.pop('choiceRationales', None)
            prior['sources'].extend(s for s in record['sources'] if s not in prior['sources'])
            inventory['duplicates'].append({'id': record['id'], 'canonicalId': prior['id'], 'method': 'identical_content'})
        else:
            if prior:
                reasons = ['conflicting_source_version']
                if not same_answer:
                    reasons.append('conflicting_duplicate_answer')
                if rationale_conflict:
                    reasons.append('conflicting_rationale')
                if visual_conflict:
                    reasons.append('conflicting_visual_dependency')
                for reason in reasons:
                    record['issues'].append(reason)
                    prior['issues'].append(reason)
                record['issues'] = sorted(set(record['issues']))
                prior['issues'] = sorted(set(prior['issues']))
                record['status'] = prior['status'] = 'needs_review'
                inventory['conflicts'].append({
                    'id': record['id'],
                    'canonicalId': prior['id'],
                    'reasons': reasons,
                    'variant': {**record},
                })
            fingerprints[fingerprint] = record
            unique.append(record)
    records = sorted(unique, key=lambda r: r['id'])
    # A source-number collision that did not consolidate is a source conflict,
    # not permission to overwrite one record with another. Keep both review
    # records addressable with a deterministic content suffix.
    ids = {}
    for record in records:
        prior = ids.get(record['id'])
        if prior:
            for variant in (prior, record):
                variant['issues'] = sorted(set(variant['issues'] + ['conflicting_source_number']))
                variant['status'] = 'needs_review'
            suffix = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
            record['id'] = f"{record['id']}-variant-{suffix}"
            inventory['conflicts'].append({'id': record['id'], 'canonicalId': prior['id'], 'reason': 'conflicting_source_number'})
        ids[record['id']] = record
    review = [{**r} for r in records if r['status'] == 'needs_review']
    for record in records:
        record.pop('_raw', None)
        record.pop('_namespace', None)
        record.pop('_source_kind', None)
        record.pop('_multiple_explicit', None)
        record.pop('_malformed_multiple', None)
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
