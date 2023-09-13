import os
import redis
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import timedelta


class Config:
    # Flask and db config
    SECRET_KEY = os.environ.get("SECRET_KEY")
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = True  # Set to True if using HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"

    # Flask-Session configurations
    SESSION_TYPE = "redis"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = "session:"
    SESSION_REDIS_URL = os.environ.get("SESSION_REDIS_URL")
    SESSION_REDIS = redis.StrictRedis.from_url(SESSION_REDIS_URL)

    # HubSpot configurations
    HUBSPOT_AUTH_URL = "https://app-eu1.hubspot.com/oauth/authorize"
    HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
    HUBSPOT_CLIENT_ID = os.environ.get("HUBSPOT_CLIENT_ID")
    HUBSPOT_CLIENT_SECRET = os.environ.get("HUBSPOT_CLIENT_SECRET")
    HUBSPOT_REDIRECT_URI = os.environ.get("HUBSPOT_REDIRECT_URI")
    HUBSPOT_SCOPES = "crm.objects.contacts.read%20crm.objects.companies.read%20crm.objects.companies.write%20crm.objects.deals.read"

    # APScheduler config
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {"default": SQLAlchemyJobStore(url=SQLALCHEMY_DATABASE_URI)}
