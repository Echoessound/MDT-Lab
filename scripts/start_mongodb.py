"""Start an isolated local MongoDB replica set on port 27018 (foreground)."""
import argparse
from pathlib import Path
import shutil
import subprocess
import time

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "outputs/mongodb")
    args = parser.parse_args()
    executable = shutil.which("mongod")
    if not executable:
        raise SystemExit("未找到 mongod。安装 MongoDB Community，或使用 docker compose up -d mongodb。")
    client = MongoClient("mongodb://127.0.0.1:27018/?directConnection=true", serverSelectionTimeoutMS=1000)
    try:
        hello = client.admin.command("hello")
    except PyMongoError:
        hello = None
    if hello is not None:
        client.close()
        if hello.get("setName") == "mdt-rs" and hello.get("isWritablePrimary"):
            print("MDT MongoDB 已就绪：127.0.0.1:27018 / mdt-rs")
            return
        raise SystemExit("27018 已有其他或未就绪 MongoDB 实例，请检查；未改变现有实例配置。")
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([executable, "--dbpath", str(directory), "--port", "27018",
        "--bind_ip", "127.0.0.1", "--replSet", "mdt-rs", "--logpath", str(directory / "mongod.log"), "--logappend"])
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("MongoDB 启动失败，请检查 outputs/mongodb/mongod.log。")
            try:
                client.admin.command("ping")
                try:
                    client.admin.command("replSetGetStatus")
                except OperationFailure as error:
                    if error.code != 94:
                        raise
                    client.admin.command("replSetInitiate", {"_id": "mdt-rs", "members": [{"_id": 0, "host": "127.0.0.1:27018"}]})
                if client.admin.command("hello").get("isWritablePrimary"):
                    break
            except PyMongoError:
                pass
            time.sleep(.25)
        else:
            raise RuntimeError("MongoDB 副本集未在 30 秒内就绪，请检查日志。")
        print("MDT MongoDB 已就绪。另开终端运行 ./start.sh；Ctrl+C 停止此实例。", flush=True)
        process.wait()
    except KeyboardInterrupt:
        pass
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    finally:
        client.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)


if __name__ == "__main__":
    main()
