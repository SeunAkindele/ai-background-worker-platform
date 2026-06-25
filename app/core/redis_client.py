import redis

from app.config import settings

# decode_responses=True → Redis returns str, not bytes
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)