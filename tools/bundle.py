"""Bundle the site into one self-contained HTML file (styles, script and data inlined).

    python tools/bundle.py                      # dist/cqr.html, a standalone page you can open offline
    python tools/bundle.py --fragment out.html  # page body only, for hosts that supply their own <head>
"""
import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')


def _between(text, tag):
    m = re.search(rf'<!-- {tag} -->(.*?)<!-- /{tag} -->', text, re.S)
    if not m:
        raise SystemExit(f'marker {tag} not found in index.html')
    return m.group(1).strip()


def bundle(fragment: bool) -> str:
    html = open(os.path.join(SITE, 'index.html')).read()
    css = open(os.path.join(SITE, 'style.css')).read()
    js = open(os.path.join(SITE, 'app.js')).read()
    data_dir = os.path.join(SITE, 'data')
    data = {'index': json.load(open(os.path.join(data_dir, 'index.json'))),
            'validation': json.load(open(os.path.join(data_dir, 'validation.json'))),
            'seasons': {}}
    for path in sorted(glob.glob(os.path.join(data_dir, '[0-9][0-9][0-9][0-9].json'))):
        data['seasons'][os.path.basename(path)[:4]] = json.load(open(path))
    blob = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    head = _between(html, 'bundle:head')
    body = _between(html, 'bundle:body')
    inner = (f'{head}\n<style>\n{css}\n</style>\n{body}\n'
             f'<script>window.CQR_DATA = {blob};</script>\n<script>\n{js}\n</script>\n')
    if fragment:
        return inner
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'</head>\n<body>\n{inner}</body>\n</html>\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', nargs='?', default=os.path.join(ROOT, 'dist', 'cqr.html'))
    ap.add_argument('--fragment', action='store_true', help='omit <html>/<head>/<body>')
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w') as fh:
        fh.write(bundle(args.fragment))
    print(f'wrote {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
