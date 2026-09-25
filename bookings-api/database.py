from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Deliberately its own connection + database, never NUA Counter's — the
# Bookings service is a standalone product; NUA's own POS is just its
# first integration partner.
mongo_url = (os.environ.get('BOOKINGS_MONGO_URL') or os.environ.get('MONGO_URL')
             or os.environ.get('MONGO_MONGODB_URI') or os.environ.get('MONGODB_URI'))
if not mongo_url:
    if os.environ.get('VERCEL'):
        raise RuntimeError('MongoDB connection is not configured')
    mongo_url = 'mongodb://localhost:27017'
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('BOOKINGS_DB_NAME', 'nua_bookings')]
