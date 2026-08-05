"""大学ランキング収集 CLI。

使い方:
    python -m scripts.collect ror [--file data/v2.11-2026-08-03-ror-data.zip]
    python -m scripts.collect the [--year 2026]
    python -m scripts.collect qs [--year 2027] [--max 2000]
    python -m scripts.collect arwu [--year 2025]
    python -m scripts.collect qs-file --file <path.csv|json> --year <N>
    python -m scripts.collect match
    python -m scripts.collect all
    python -m scripts.collect stats
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import services  # noqa: E402
from app.collectors import arwu as arwu_collector  # noqa: E402
from app.collectors import qs as qs_collector  # noqa: E402
from app.collectors import the as the_collector  # noqa: E402
from app.config import DEFAULT_ROR_ZIP, DATA_DIR  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402


def _db():
    init_db()
    return SessionLocal()


def cmd_ror(args):
    path = args.file or str(DEFAULT_ROR_ZIP)
    db = _db()
    try:
        info = services.import_ror(db, path)
    finally:
        db.close()
    print(
        f"[ror] version={info['version']} universities={info['universities']} "
        f"(created={info['created']}, updated={info['updated']})"
    )


def cmd_qs(args):
    from app.collectors.qs import fetch_rankings

    db = _db()
    try:
        result = fetch_rankings(args.year, max_entries=args.max, nid=args.nid)
        info = services.import_rankings(db, result)
    finally:
        db.close()
    print(f"[qs] year={info['year']} records={info['records']} (version={result.version})")


def cmd_qs_file(args):
    db = _db()
    try:
        result = qs_collector.load_from_file(args.file, year=args.year)
        info = services.import_rankings(db, result)
    finally:
        db.close()
    print(f"[qs-file] year={info['year']} records={info['records']}")


def cmd_the(args):
    db = _db()
    try:
        result = the_collector.fetch_rankings(args.year, max_entries=args.max)
        info = services.import_rankings(db, result)
    finally:
        db.close()
    print(f"[the] year={info['year']} records={info['records']}")


def cmd_arwu(args):
    db = _db()
    try:
        result = arwu_collector.fetch_rankings(args.year, max_entries=args.max)
        info = services.import_rankings(db, result)
    finally:
        db.close()
    print(f"[arwu] year={info['year']} records={info['records']}")


def cmd_match(args):
    db = _db()
    try:
        info = services.run_matcher(db)
    finally:
        db.close()
    print(f"[match] matched={info['matched']}/{info['total']}")


def cmd_all(args):
    cmd_ror(args)
    cmd_the(args)
    cmd_qs(args)
    cmd_arwu(args)
    cmd_match(args)


def cmd_stats(args):
    from sqlalchemy import func, select

    from app.database import DataSource, Ranking, University

    db = _db()
    try:
        n_uni = db.execute(select(func.count(University.id))).scalar()
        print(f"universities (ROR): {n_uni}")
        rows = (
            db.execute(
                select(Ranking.source, Ranking.year, func.count(Ranking.id))
                .group_by(Ranking.source, Ranking.year)
                .order_by(Ranking.source, Ranking.year)
            )
            .all()
        )
        for s, y, c in rows:
            print(f"  ranking {s} {y}: {c}")
        print("datasets:")
        for d in db.execute(select(DataSource).order_by(DataSource.imported_at)).scalars():
            print(
                f"  - {d.name} {d.version} year={d.year} records={d.record_count} "
                f"published={d.published_at} imported={d.imported_at:%Y-%m-%d %H:%M}"
            )
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(prog="collect")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ror", help="RoR データダンプをインポート")
    p.add_argument("--file", help="ZIP ファイルパス")
    p.set_defaults(func=cmd_ror)

    p = sub.add_parser("qs", help="QS ランキングをライブ取得")
    p.add_argument("--year", type=int, default=0, help="ランキングエディション年 (未指定時は自動)")
    p.add_argument("--max", type=int, default=2000)
    p.add_argument("--nid", help="QS Drupal ノード ID (省略時は自動検出)")
    p.set_defaults(func=cmd_qs)

    p = sub.add_parser("qs-file", help="QS ランキングを静的ファイルから取込 (year 必須)")
    p.add_argument("--file", required=True)
    p.add_argument("--year", type=int, required=True)
    p.set_defaults(func=cmd_qs_file)

    p = sub.add_parser("the", help="THE ランキングを公式 API から取得")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--max", type=int, default=5000)
    p.set_defaults(func=cmd_the)

    p = sub.add_parser("arwu", help="ARWU ランキングを公式 API から取得")
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--max", type=int, default=2000)
    p.set_defaults(func=cmd_arwu)

    p = sub.add_parser("match", help="ランキングを ROR 大学にマッチング")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("all", help="ror + the + qs + arwu + match を順に実行")
    p.add_argument("--year", type=int, default=0)
    p.add_argument("--nid", help="QS Drupal ノード ID (省略時は自動検出)")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("stats")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.file = getattr(args, "file", None)
    args.year = getattr(args, "year", 0) or 0
    args.max = getattr(args, "max", 2000)
    args.nid = getattr(args, "nid", None)
    args.func(args)


if __name__ == "__main__":
    main()
