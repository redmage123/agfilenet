"""Command line: python -m agfilenet ingest | analyse | models | serve.

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
    p = sub.add_parser("models", help="download the local models (needs the network, once)")
    p.add_argument("--no-llm", action="store_true", help="leave out the language model (about 1 GB)")
    p = sub.add_parser("serve", help="run the web application")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.command == "ingest":
        from . import ingest
        print(f"Ingesting {config.DATA_DIR} into {config.DB_PATH}")
        ingest.run(force=args.force, job_id=ingest.new_job())
    elif args.command == "analyse":
        from . import ingest
        ingest.upgrade() if _stale() else _analyse()
    elif args.command == "models":
        from . import models
        print(f"Fetching models into {config.MODEL_DIR}")
        models.fetch_all(llm=not args.no_llm)
    else:
        import uvicorn
        uvicorn.run("agfilenet.api:app", host=args.host, port=args.port)


def _stale():
    from . import ingest, store
    with store.Session() as session:
        return ingest.needs_upgrade(session.lib)


def _analyse():
    from . import ingest, insight, store
    with store.Session(write=True) as session:
        ingest.read_names(session.lib)
        ingest.analyse(session.lib)
        ingest.refresh_text_index(session.lib)
        insight.refresh(session.lib)


if __name__ == "__main__":
    main()
