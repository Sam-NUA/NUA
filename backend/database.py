from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = (os.environ.get('MONGO_URL')
             or os.environ.get('MONGO_MONGODB_URI')
             or os.environ.get('MONGODB_URI'))
if not mongo_url:
    raise RuntimeError('MongoDB connection is not configured')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
