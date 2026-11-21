"""Command line: python -m agfilenet ingest | analyse | serve.

The object database is a single file opened by one process at a time, so
stop the server before running `ingest` or `analyse` here (or start the
ingest from the web page instead).
"""
import argparse

from . import config


def main():
    parser = argparse.ArgumentParser(prog="agfilenet")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="read, OCR and index everything under the data directory")
    p.add_argument("--force", action="store_true", help="re-read files even if unchanged")
    sub.add_parser("analyse", help="re-derive metadata from stored page text (no OCR)")
    p = sub.add_parser("serve", help="run the web application")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.command == "ingest":
        from . import ingest
        print(f"Ingesting {config.DATA_DIR} into {config.DB_PATH}")
        ingest.run(force=args.force, job_id=ingest.new_job())
    elif args.command == "analyse":
        from . import ingest, store
        with store.Session(write=True) as session:
            ingest.analyse(session.lib)
    else:
        import uvicorn
        uvicorn.run("agfilenet.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
