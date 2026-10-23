from pathlib import Path
import argparse
import json
import sys
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="RetailPulse: live retail sales and forecasting")
    parser.add_argument("--data-dir", default="data", help="Separate data folder for this store or dataset")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Create a labelled synthetic dataset and train forecasts")
    demo.add_argument("--days", type=int, default=365)
    download = commands.add_parser("download-uci", help="Download the real UCI historical Excel dataset")
    download.add_argument("--destination", default="downloads")
    importer = commands.add_parser("import-uci", help="Import historical UCI sales into a separate data folder")
    importer.add_argument("--file", required=True)
    importer.add_argument("--top-products", type=int, default=12)
    own = commands.add_parser("import-sales", help="Import your store's complete transaction CSV")
    own.add_argument("--file", required=True)
    own.add_argument("--complete-through", required=True, help="Last verified complete sales date, YYYY-MM-DD")
    own.add_argument("--currency", default="INR")
    own.add_argument("--timezone", default="Asia/Kolkata")
    own.add_argument("--continuous", action="store_true", help="Keep recording every sale in the app; CSV must cover through yesterday")
    commands.add_parser("train", help="Retrain forecasts using completed calendar days")
    setup = commands.add_parser("init-shop",help="Create an empty real shop (no sample sales)")
    setup.add_argument("--name",required=True)
    setup.add_argument("--currency",default="INR")
    setup.add_argument("--timezone",default="Asia/Kolkata")
    commands.add_parser("backup",help="Create a consistent database backup")
    restore = commands.add_parser("restore-backup",help="Restore a backup into a NEW empty data folder")
    restore.add_argument("--file",required=True)
    exporter = commands.add_parser("export", help="Export CSV tables for Power BI or Excel")
    exporter.add_argument("--destination")
    server = commands.add_parser("serve", help="Open the live browser dashboard")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    server.add_argument("--find-port",action="store_true",help="Try the next nine ports if the chosen port is busy")
    stream = commands.add_parser("simulate", help="Continuously generate clearly labelled demo sales")
    stream.add_argument("--interval", type=float, default=2)
    stream.add_argument("--count", type=int)
    args = parser.parse_args()
    try:
        if args.command == "download-uci":
            from .data import download_uci
            print(download_uci(args.destination))
            return
        if args.command == "restore-backup":
            from .backups import restore_backup
            print(json.dumps(restore_backup(args.file,args.data_dir),indent=2))
            return 0
        store = Store(args.data_dir)
        if args.command == "init-shop":
            import uuid
            print(json.dumps(store.initialize_shop({"request_id":str(uuid.uuid4()),"shop_name":args.name,"currency":args.currency,"timezone":args.timezone}),indent=2))
        elif args.command == "backup":
            from .backups import create_backup
            print(json.dumps(create_backup(store),indent=2))
        elif args.command == "simulate":
            from .stream import simulate
            simulate(args.data_dir, args.interval, args.count)
        elif args.command == "demo":
            from .data import seed_demo
            from .forecast import train
            seed_demo(store, args.days)
            print("Synthetic demo created. Training with date-based validation...", flush=True)
            print(json.dumps(train(store), indent=2))
        elif args.command == "import-uci":
            from .data import import_uci
            print(json.dumps(import_uci(store, args.file, args.top_products), indent=2))
            print("Next: run train with the same --data-dir.")
        elif args.command == "train":
            from .forecast import train
            print(json.dumps(train(store), indent=2))
        elif args.command == "import-sales":
            from .data import import_sales
            print(json.dumps(import_sales(store,args.file,args.complete_through,args.currency,args.timezone,args.continuous),indent=2))
            print("Enter known opening stock in the dashboard before recording new sales.")
        elif args.command == "export":
            from .web import export_rows, csv_output
            target = Path(args.destination) if args.destination else store.directory/"exports"
            target.mkdir(parents=True, exist_ok=True)
            for table in ("sales", "daily_sales", "net_daily_sales", "returns", "stock_movements", "inventory", "forecast", "holdout"):
                (target/f"{table}.csv").write_bytes(csv_output(export_rows(store, table)))
            print(f"Exported eight CSV files to {target.resolve()}")
        else:
            from .web import serve
            serve(store.directory, args.host, args.port, args.open, args.find_port)
    except KeyboardInterrupt:
        print("\nRetailPulse stopped.")
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
