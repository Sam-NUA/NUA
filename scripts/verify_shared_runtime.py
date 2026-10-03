#!/usr/bin/env python3
"""Real Mongo, isolated worker processes and cold-restart coordination test.

TEST_MONGO_URL must point to a disposable test Mongo server. This script
creates and drops only its own randomly named database; never seeds live POS
accounts or sends payment requests. It does not prove Vercel instance placement.
"""
import asyncio
import multiprocessing as mp
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def worker(uri, name, index, now, output):
    async def run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from services.shared_runtime import SharedRuntime
        client = AsyncIOMotorClient(uri)
        runtime = SharedRuntime(client[name])
        try:
            answers = await asyncio.gather(*[
                runtime.allow("same-user", 25, 60, now) for _ in range(20)])
            await asyncio.gather(*[
                runtime.publish("tenant-a", {"type": "probe", "value": f"{index}-{n}"})
                for n in range(10)])
            output.put(sum(allowed for allowed, _ in answers))
        finally:
            client.close()
    asyncio.run(run())


def main():
    from pymongo import MongoClient
    uri = os.environ["TEST_MONGO_URL"]
    name = f"nua_coordination_test_{uuid.uuid4().hex}"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    context = mp.get_context("spawn")
    output = context.Queue()
    try:
        now = __import__("time").time()
        workers = [context.Process(target=worker, args=(uri, name, i, now, output)) for i in range(4)]
        for process in workers:
            process.start()
        for process in workers:
            process.join(30)
            if process.is_alive():
                process.terminate()
                process.join()
            assert process.exitcode == 0, "Worker did not finish successfully"
        assert sum(output.get(timeout=5) for _ in workers) == 25
        # A fifth, freshly started process cannot reset the exhausted bucket.
        cold = context.Process(target=worker, args=(uri, name, 4, now, output))
        cold.start()
        cold.join(30)
        if cold.is_alive():
            cold.terminate()
            cold.join()
        assert cold.exitcode == 0
        assert output.get(timeout=5) == 0

        async def verify():
            from motor.motor_asyncio import AsyncIOMotorClient
            from services.shared_runtime import SharedRuntime
            reader = AsyncIOMotorClient(uri)
            runtime = SharedRuntime(reader[name])
            try:
                await runtime.ensure_indexes()
                events = await runtime.read("tenant-a", "empty")
                assert len(events["events"]) == 50
                assert len({e["value"] for e in events["events"]}) == 50
                assert not (await runtime.read("tenant-b", "empty"))["events"]
                assert not (await runtime.read("tenant-a", events["cursor"]))["events"]
                assert (await runtime.allow("same-user", 25, 60, now + 61))[0]
                for n in range(101):
                    await runtime.publish("tenant-a", {"type": "overflow", "n": n})
                assert (await runtime.read("tenant-a", events["cursor"]))["reset"]
                print("PASS: 5 processes, 100 concurrent limit attempts, exactly 25 allowed;")
                print("PASS: cold restart preserves limit; 50 unique cross-process events;")
                print("PASS: tenant isolation, cursor replay, expiry, and overflow refresh.")
            finally:
                reader.close()
        asyncio.run(verify())
    finally:
        client.drop_database(name)
        client.close()


if __name__ == "__main__":
    main()
