#!/usr/bin/env python3
"""Generate IF Archive Index entries for an IFComp year from the big zip.

Fetches game slugs and IFDB TUIDs from ifcomp.org, lists per-game sub-zips
inside the IFComp big zip, and looks up title and author on IFDB (tag:IFComp
YYYY search). In production this runs on the end-of-comp zip; a start-of-comp
zip is fine for testing.

Runtime platform and "Contains..." lines are inferred from IFComp platform
metadata and sub-zip member names. For Glulx, Z-Code, TADS, and ADRIFT
entries, release/serial lines come from scripts/blorple.py when a story
file is present in the sub-zip.

Example:
  python3 scripts/ifcomp-index-generator.py 2026 /path/to/IFComp2026.zip \\
      -o /private/tmp/tp/ifcomp-2026-index.txt

  python3 scripts/ifcomp-index-generator.py 2026 /path/to/IFComp2026.zip \\
      --report-json /private/tmp/tp/ifcomp-2026-report.json
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

INFORM_PLATFORMS = frozenset({'inform', 'quixe', 'parchment', 'inform-website'})
# Inform Z-code / Glulx story files (and blorbs wrapping them).
INFORM_STORY_EXTENSIONS = frozenset({
    'gblorb', 'zblorb', 'ulx', 'glulx', 'blorb',
    'z1', 'z2', 'z3', 'z4', 'z5', 'z6', 'z7', 'z8',
})
# Other downloadable parser story formats.
PARSER_STORY_EXTENSIONS = INFORM_STORY_EXTENSIONS | frozenset({
    'taf', 't3', 'gam', 'hex', 'a3c',
})
WEB_PLATFORM_LABELS = {
    'twine': 'Twine',
    'ink': 'Ink',
    'texture': 'Texture',
    'choicescript': 'ChoiceScript',
    'adventuron': 'Adventuron',
    'alan': 'Alan',
    'hugo': 'Hugo',
    'quest': 'Quest',
    'quest-online': 'Quest',
    'unity': 'Unity',
}
BLORPLE_RUNTIMES = frozenset({
    'Glulx',
    'Z-Code',
    'TADS',
    'TADS 2',
    'TADS 3',
    'ADRIFT',
})
# Story files that scripts/blorple.py can read (priority order).
RELEASE_SERIAL_SUFFIXES = (
    '.gblorb', '.zblorb', '.blorb', '.ulx', '.glulx',
    '.z8', '.z5', '.z3', '.z4', '.z6', '.z7', '.z1', '.z2',
    '.t3', '.gam', '.taf',
)

_blorple_mod = None


def fetch_json(url: str, timeout: int = 60) -> object:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'ifarchive-admintool/ifcomp-index-generator'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_ifcomp_games(year: int, timeout: int) -> list[dict]:
    url = f'https://ifcomp.org/comp/{year}/json'
    data = fetch_json(url, timeout=timeout)
    if not isinstance(data, list):
        raise ValueError(f'unexpected IFComp JSON from {url!r}')
    return data


def fetch_ifdb_by_tuid(year: int, timeout: int) -> dict[str, dict[str, str | None]]:
    query = urllib.parse.quote(f'tag:IFComp {year}')
    url = f'https://ifdb.org/search?searchbar={query}&json'
    data = fetch_json(url, timeout=timeout)
    if not isinstance(data, dict) or 'games' not in data:
        raise ValueError(f'unexpected IFDB JSON from {url!r}')
    by_tuid: dict[str, dict[str, str | None]] = {}
    for game in data['games']:
        tuid = game.get('tuid')
        if not tuid:
            continue
        by_tuid[tuid] = {
            'title': game.get('title'),
            'author': game.get('author'),
        }
    return by_tuid


def list_game_zips(big_zip: Path) -> dict[str, str]:
    """Return slug -> archive member path (e.g. Games/Enkii.zip)."""
    zips: dict[str, str] = {}
    with zipfile.ZipFile(big_zip) as zf:
        for name in zf.namelist():
            if not name.startswith('Games/') or not name.endswith('.zip'):
                continue
            slug = Path(name).stem
            zips[slug] = name
    return zips


def list_sub_zip_contents(big_zip: Path) -> dict[str, list[str]]:
    """Return {Games/Slug.zip: [member names, ...]} for each game sub-zip."""
    result: dict[str, list[str]] = {}
    with zipfile.ZipFile(big_zip) as outer:
        game_zips = sorted(
            name
            for name in outer.namelist()
            if name.startswith('Games/') and name.endswith('.zip')
        )
        for member in game_zips:
            with zipfile.ZipFile(io.BytesIO(outer.read(member))) as inner:
                result[member] = inner.namelist()
    return result


def _skip_member(path: str) -> bool:
    if not path or path.endswith('/'):
        return True
    if '__MACOSX' in path:
        return True
    base = path.rsplit('/', 1)[-1]
    return base in {'.DS_Store', 'Thumbs.db', 'desktop.ini'}


def leaf_names(members: list[str]) -> list[str]:
    return [
        path.rsplit('/', 1)[-1]
        for path in members
        if not _skip_member(path)
    ]


def member_paths_lower(members: list[str]) -> list[str]:
    return [path.lower() for path in members if not _skip_member(path)]


def file_extension(name: str) -> str:
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].lower()


def has_extension(leaves: list[str], *extensions: str) -> bool:
    ext_set = {ext.lower().lstrip('.') for ext in extensions}
    return any(file_extension(name) in ext_set for name in leaves)


def inform_runtime(is_zcode: object) -> str:
    return 'Z-Code' if is_zcode else 'Glulx'


def runtime_platform(game: dict, members: list[str]) -> tuple[str, list[str]]:
    """Infer IF Archive-style runtime platform label."""
    platform = (game.get('platform') or 'other').lower()
    is_zcode = bool(game.get('is_zcode'))
    leaves = leaf_names(members)
    paths_l = member_paths_lower(members)
    warnings: list[str] = []

    if platform in INFORM_PLATFORMS:
        return inform_runtime(is_zcode), warnings

    if platform in ('adrift', 'adrift-online'):
        return 'ADRIFT', warnings

    if platform in ('tads', 'tads-web-ui'):
        if has_extension(leaves, 't3'):
            return 'TADS 3', warnings
        if has_extension(leaves, 'gam'):
            return 'TADS 2', warnings
        return 'TADS 3' if platform == 'tads-web-ui' else 'TADS', warnings

    if platform in WEB_PLATFORM_LABELS:
        return WEB_PLATFORM_LABELS[platform], warnings

    if platform == 'windows':
        return 'Windows executable', warnings

    if platform == 'website':
        if has_extension(leaves, *INFORM_STORY_EXTENSIONS):
            return inform_runtime(is_zcode), warnings
        return 'Web-based', warnings

    if platform == 'other':
        if has_extension(leaves, 'exe'):
            return 'Windows executable', warnings
        if has_extension(leaves, 'dmg'):
            return 'Macintosh executable', warnings
        if has_extension(leaves, 't3'):
            return 'TADS 3', warnings
        if has_extension(leaves, 'gam'):
            return 'TADS 2', warnings
        if has_extension(leaves, 'taf'):
            return 'ADRIFT', warnings
        if has_extension(leaves, *INFORM_STORY_EXTENSIONS):
            return inform_runtime(is_zcode), warnings
        if has_extension(leaves, 'html', 'htm'):
            return 'Web-based', warnings
        warnings.append('platform "other" with no recognized story file type')
        return 'Unknown', warnings

    label = platform.replace('-', ' ').title()
    warnings.append(f'unhandled IFComp platform {platform!r}')
    return label, warnings


def _has_html_interpreter(platform: str, paths_l: list[str], leaves: list[str]) -> bool:
    joined = '\n'.join(paths_l)
    has_interpreter_dir = (
        'interpreter/' in joined or joined.endswith('/interpreter')
    )
    has_interpreter_assets = any(
        token in joined
        for token in (
            'quixe',
            'parchment',
            'glkote',
            'zvm.js',
            'parchment.css',
            '.gblorb.js',
            '.zblorb.js',
        )
    )
    if has_interpreter_dir and has_interpreter_assets:
        return True
    if platform == 'inform-website' and (has_interpreter_dir or has_interpreter_assets):
        return True

    # Dialog and similar web interpreters (e.g. aaengine.js + index.html).
    if 'aaengine.js' in joined and any(
        name.lower() in {'index.html', 'play.html'} for name in leaves
    ):
        return True

    # Packaged web play folder with an explicit interpreter license.
    if 'web/index.html' in joined and (
        'web/interpreter_license.txt' in joined
        or 'interpreter_license.txt' in joined
    ):
        return True

    return False


def _has_standalone_map(members: list[str]) -> bool:
    """True when the zip has a separately packaged map at the top level."""
    for path in members:
        if _skip_member(path):
            continue
        if '/' in path.rstrip('/'):
            continue
        base = path.rsplit('/', 1)[-1].lower()
        if base in {'map.html', 'map.htm', 'map.pdf'}:
            return True
        if base.endswith('.pdf') and re.search(r'map', base):
            return True
    return False


def _basename_matches(leaves: list[str], pattern: str) -> bool:
    rx = re.compile(pattern, re.IGNORECASE)
    return any(rx.search(name) for name in leaves)


def describe_contents(game: dict, members: list[str]) -> list[str]:
    """Infer a "Contains ..." item list from zip member names."""
    platform = (game.get('platform') or 'other').lower()
    leaves = leaf_names(members)
    paths_l = member_paths_lower(members)
    items: list[str] = []

    has_parser_story = has_extension(leaves, *PARSER_STORY_EXTENSIONS)
    has_interpreter = _has_html_interpreter(platform, paths_l, leaves)

    if has_parser_story:
        items.append('story file')

    if has_interpreter:
        items.append('HTML interpreter')

    if _basename_matches(leaves, r'walkthrough|solution'):
        items.append('walkthrough')
    if _basename_matches(leaves, r'hint'):
        items.append('hints')
    if _has_standalone_map(members):
        items.append('map')
    if _basename_matches(leaves, r'manual'):
        items.append('manual')
    if any(
        file_extension(name) in {'ni', 'tws', 'ink'}
        or name.lower() in {'source.txt', 'source.inform'}
        for name in leaves
    ):
        items.append('source code')

    if items == ['story file']:
        return []
    return items


def format_contains(items: list[str]) -> str:
    if not items:
        return ''
    if len(items) == 1:
        return f'Contains {items[0]}.'
    if len(items) == 2:
        return f'Contains {items[0]} and {items[1]}.'
    return f'Contains {", ".join(items[:-1])}, and {items[-1]}.'


def load_blorple_module():
    """Load scripts/blorple.py as a module."""
    global _blorple_mod
    if _blorple_mod is not None:
        return _blorple_mod
    path = Path(__file__).resolve().parent / 'blorple.py'
    spec = importlib.util.spec_from_file_location('blorple', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _blorple_mod = mod
    return mod


def is_release_serial_story(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in RELEASE_SERIAL_SUFFIXES)


def choose_release_serial_member(members: list[str]) -> str | None:
    """Pick the best story member for blorple.py."""
    scored: list[tuple[int, str]] = []
    for name in members:
        if _skip_member(name):
            continue
        lower = name.lower()
        for i, suf in enumerate(RELEASE_SERIAL_SUFFIXES):
            if lower.endswith(suf):
                scored.append((i, name))
                break
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][1]


def read_sub_zip_member(
    big_zip: Path,
    game_zip_path: str,
    member: str,
) -> bytes | None:
    """Extract one member from a game sub-zip inside the IFComp big zip."""
    try:
        with zipfile.ZipFile(big_zip) as outer:
            sub_data = outer.read(game_zip_path)
        with zipfile.ZipFile(io.BytesIO(sub_data)) as inner:
            names = set(inner.namelist())
            target = member if member in names else None
            if target is None:
                base = member.rsplit('/', 1)[-1]
                matches = [
                    n for n in names
                    if not n.endswith('/') and n.rsplit('/', 1)[-1] == base
                ]
                target = matches[0] if matches else None
            if target is None:
                return None
            return inner.read(target)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def format_release_serial_line(
    release: int | None,
    serial: str | None,
) -> str | None:
    serial_clean = (serial or '').strip() or None
    if release is not None and serial_clean:
        return f'Release {release} / Serial number {serial_clean}.'
    if release is not None:
        return f'Release {release}.'
    if serial_clean:
        return f'Serial number {serial_clean}.'
    return None


def release_serial_for_game(
    big_zip: Path,
    zip_path: str,
    members: list[str],
    runtime: str,
) -> tuple[int | None, str | None, str | None, list[str]]:
    """Run blorple on the best story file in a game sub-zip, if applicable."""
    if runtime not in BLORPLE_RUNTIMES:
        return None, None, None, []

    member = choose_release_serial_member(members)
    if member is None:
        return None, None, None, [f'{zip_path}: no story file for blorple']

    data = read_sub_zip_member(big_zip, zip_path, member)
    if data is None:
        return None, None, None, [
            f'{zip_path}: could not extract {member!r} for blorple',
        ]

    blorple = load_blorple_module()
    suffix = ''.join(Path(member).suffixes) or Path(member).suffix or '.bin'
    warnings: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix='ifcomp-blorple-') as td:
            story_path = Path(td) / f'story{suffix}'
            story_path.write_bytes(data)
            release, serial = blorple.release_and_serial(story_path)
    except blorple.ExtractError as exc:
        warnings.append(f'{zip_path}: blorple ({member}): {exc}')
        return None, None, None, warnings
    except OSError as exc:
        warnings.append(f'{zip_path}: blorple ({member}): {exc}')
        return None, None, None, warnings

    line = format_release_serial_line(release, serial)
    return release, serial, line, warnings


def format_description_line(
    title: str,
    author: str | None,
    runtime: str,
) -> str:
    if author:
        author = author.rstrip('.')
        return f'{title}, by {author}. {runtime}.'
    return f'{title}. {runtime}.'


def format_entry(
    zip_path: str,
    tuid: str | None,
    title: str,
    author: str | None,
    runtime: str,
    release_serial_line: str | None,
    contains: list[str],
) -> str:
    lines = [f'# {zip_path}']
    if tuid:
        lines.append(f'tuid: {tuid}')
    lines.append('')
    lines.append(format_description_line(title, author, runtime))
    if release_serial_line:
        lines.append(release_serial_line)
    contains_line = format_contains(contains)
    if contains_line:
        lines.append(contains_line)
    lines.append('')
    return '\n'.join(lines)


def analyze_game(
    game: dict,
    zip_path: str,
    members: list[str],
    ifdb_games: dict[str, dict[str, str | None]],
    big_zip: Path,
) -> tuple[dict, list[str]]:
    """Return a review report record and any warnings for one game."""
    warnings: list[str] = []
    slug = game.get('slug') or ''

    runtime, runtime_warnings = runtime_platform(game, members)
    warnings.extend(f'{zip_path}: {msg}' for msg in runtime_warnings)

    contains = describe_contents(game, members)

    release, serial, release_serial_line, blorple_warnings = release_serial_for_game(
        big_zip,
        zip_path,
        members,
        runtime,
    )
    warnings.extend(blorple_warnings)

    tuid = game.get('ifdb_id')
    if not tuid:
        warnings.append(f'{zip_path}: no ifdb_id in IFComp JSON')
        title = game.get('title') or slug
        author = None
    else:
        ifdb = ifdb_games.get(tuid)
        if ifdb is None:
            warnings.append(f'{zip_path}: TUID {tuid!r} not found on IFDB')
            title = game.get('title') or slug
            author = None
        else:
            title = ifdb.get('title') or game.get('title') or slug
            author = ifdb.get('author')

    description_line = format_description_line(title, author, runtime)
    contains_line = format_contains(contains)
    index_entry = format_entry(
        zip_path,
        tuid=tuid,
        title=title,
        author=author,
        runtime=runtime,
        release_serial_line=release_serial_line,
        contains=contains,
    )

    report_contents = [
        path for path in members if not _skip_member(path)
    ]

    record = {
        'slug': slug,
        'zip_path': zip_path,
        'input': {
            'ifcomp': {
                'platform': game.get('platform'),
                'is_zcode': game.get('is_zcode'),
                'title': game.get('title'),
                'ifdb_id': game.get('ifdb_id'),
            },
            'contents': report_contents,
        },
        'output': {
            'title': title,
            'author': author,
            'tuid': tuid,
            'runtime_platform': runtime,
            'release': release,
            'serial': serial,
            'release_serial_line': release_serial_line,
            'contains_items': contains,
            'contains_line': contains_line or None,
            'description_line': description_line,
            'index_entry': index_entry,
        },
        'warnings': [w for w in warnings if w.startswith(zip_path)],
    }
    return record, warnings


def collect_game_data(
    year: int,
    big_zip: Path,
    timeout: int,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """Fetch metadata and analyze every IFComp game in the big zip."""
    ifcomp_games = fetch_ifcomp_games(year, timeout=timeout)
    ifdb_games = fetch_ifdb_by_tuid(year, timeout=timeout)
    zip_by_slug = list_game_zips(big_zip)
    sub_zip_contents = list_sub_zip_contents(big_zip)

    warnings: list[str] = []
    records: list[dict] = []

    ifcomp_slugs = {game['slug'] for game in ifcomp_games if game.get('slug')}
    for slug in sorted(zip_by_slug.keys() - ifcomp_slugs):
        warnings.append(f'zip {zip_by_slug[slug]!r} has no IFComp entry')
    for slug in sorted(ifcomp_slugs - zip_by_slug.keys()):
        warnings.append(f'IFComp slug {slug!r} has no sub-zip in {big_zip}')

    for game in sorted(ifcomp_games, key=lambda g: g.get('slug', '')):
        slug = game.get('slug')
        if not slug:
            warnings.append(f'IFComp entry missing slug: {game!r}')
            continue

        zip_path = zip_by_slug.get(slug)
        if zip_path is None:
            continue

        members = sub_zip_contents.get(zip_path, [])
        record, game_warnings = analyze_game(
            game,
            zip_path,
            members,
            ifdb_games,
            big_zip,
        )
        warnings.extend(game_warnings)
        records.append(record)

    return records, warnings, zip_by_slug


def generate_report(
    year: int,
    big_zip: Path,
    timeout: int,
) -> tuple[dict, list[str]]:
    records, warnings, _zip_by_slug = collect_game_data(year, big_zip, timeout)
    report = {
        'year': year,
        'big_zip': str(big_zip),
        'game_count': len(records),
        'games': records,
        'warnings': warnings,
    }
    return report, warnings


def format_directory_header(year: int) -> str:
    """Index preamble for the competition directory (end-of-comp snapshot)."""
    return '\n'.join(
        [
            f'ifwiki: IFComp {year}',
            '',
            f'The entries in the {year} Interactive Fiction Competition.',
            '(As they stood when voting closed.)',
            '',
        ]
    )


def format_big_zip_entry(year: int) -> str:
    """Index entry for IFComp{year}.zip (start-of-comp package)."""
    return '\n'.join(
        [
            f'# IFComp{year}.zip',
            'unbox-link: false',
            '',
            f'All of the entries in the {year} competition in one',
            'package, as released at the start of the competition.',
            '',
        ]
    )


def assemble_index_text(year: int, game_entries: list[str]) -> str:
    parts = [format_directory_header(year), format_big_zip_entry(year)]
    parts.extend(game_entries)
    text = '\n'.join(parts)
    return text + ('\n' if game_entries else '')


def generate_index(
    year: int,
    big_zip: Path,
    timeout: int,
) -> tuple[str, list[str]]:
    records, warnings, _zip_by_slug = collect_game_data(year, big_zip, timeout)
    entries = [record['output']['index_entry'] for record in records]
    return assemble_index_text(year, entries), warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Generate IF Archive Index entries for IFComp games by matching '
            'IFComp slugs to sub-zips and IFDB TUIDs to titles/authors.'
        )
    )
    parser.add_argument('year', type=int, help='competition year (e.g. 2026)')
    parser.add_argument(
        'big_zip',
        type=Path,
        help=(
            'path to the IFComp big zip (e.g. IFComp2026.zip); '
            'end-of-comp in production, start-of-comp OK for testing'
        ),
    )
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        help='write Index text to this file (default: stdout)',
    )
    parser.add_argument(
        '--report-json',
        type=Path,
        help='write a JSON report for debugging',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=60,
        help='HTTP timeout in seconds (default: 60)',
    )
    args = parser.parse_args(argv)

    if not args.big_zip.is_file():
        print(f'error: not a file: {args.big_zip}', file=sys.stderr)
        return 1

    if not args.output and not args.report_json:
        print('error: specify -o/--output and/or --report-json', file=sys.stderr)
        return 1

    try:
        warnings: list[str] = []
        report = None
        index_text = ''

        if args.report_json and args.output:
            records, warnings, _zip_by_slug = collect_game_data(
                args.year,
                args.big_zip,
                timeout=args.timeout,
            )
            report = {
                'year': args.year,
                'big_zip': str(args.big_zip),
                'game_count': len(records),
                'games': records,
                'warnings': warnings,
            }
            entries = [record['output']['index_entry'] for record in records]
            index_text = assemble_index_text(args.year, entries)
        elif args.report_json:
            report, warnings = generate_report(
                args.year,
                args.big_zip,
                timeout=args.timeout,
            )
        else:
            index_text, warnings = generate_index(
                args.year,
                args.big_zip,
                timeout=args.timeout,
            )
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    except zipfile.BadZipFile as exc:
        print(f'error: {args.big_zip}: {exc}', file=sys.stderr)
        return 1

    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
        print(
            f'wrote report for {report["game_count"]} games to {args.report_json}',
            file=sys.stderr,
        )

    if args.output:
        args.output.write_text(index_text, encoding='utf-8')
    elif not args.report_json:
        sys.stdout.write(index_text)

    return 1 if warnings else 0


if __name__ == '__main__':
    sys.exit(main())
