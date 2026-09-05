"""Render a source page for visual review; output is a local review artifact."""
import argparse
from pathlib import Path
import fitz

parser = argparse.ArgumentParser()
parser.add_argument('filename')
parser.add_argument('page', type=int)
parser.add_argument('--output', default='.local/source-review.png')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
path = root/'raw pdfs'/args.filename
if path.parent != root/'raw pdfs':
    raise SystemExit('Use a source filename, not a path.')
doc = fitz.open(path)
if not 1 <= args.page <= len(doc):
    raise SystemExit('Page is outside the document.')
output = root/args.output
output.parent.mkdir(parents=True, exist_ok=True)
doc[args.page-1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(output)
print(output)
