"""Initialize the disposable MongoDB replica set used by CI only."""
import time
from pymongo import MongoClient

client = MongoClient('mongodb://127.0.0.1:27018/?directConnection=true', serverSelectionTimeoutMS=1000)
for _ in range(30):
    try:
        client.admin.command('ping')
        break
    except Exception:
        time.sleep(.5)
else:
    raise RuntimeError('Test MongoDB did not start')
client.admin.command('replSetInitiate', {'_id': 'nua-test', 'members': [{'_id': 0, 'host': '127.0.0.1:27018'}]})
for _ in range(60):
    if client.admin.command('hello').get('isWritablePrimary'):
        break
    time.sleep(.5)
else:
    raise RuntimeError('Test replica set has no primary')
