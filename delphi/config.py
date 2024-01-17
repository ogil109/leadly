import os
from datetime import timedelta

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from pytz import utc

from delphi import db


class Config:
    # Flask and db config
    SECRET_KEY = os.environ.get("SECRET_KEY")
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = True  # Set to True if using HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"

    # Flask-Session configurations
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_USE_SIGNER = True
    SESSION_SQLALCHEMY = db
    SESSION_SQLALCHEMY_TABLE = "flask_session"

    # HubSpot configurations
    HUBSPOT_AUTH_URL = "https://app-eu1.hubspot.com/oauth/authorize"
    HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
    HUBSPOT_CLIENT_ID = os.environ.get("HUBSPOT_CLIENT_ID")
    HUBSPOT_CLIENT_SECRET = os.environ.get("HUBSPOT_CLIENT_SECRET")
    HUBSPOT_REDIRECT_URI = os.environ.get("HUBSPOT_REDIRECT_URI")
    HUBSPOT_SCOPES = "crm.objects.contacts.read%20crm.objects.companies.read%20crm.objects.companies.write%20crm.objects.deals.read"

    # Flask-APScheduler config (native APScheduler config options in dict form)
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {"default": SQLAlchemyJobStore(url=SQLALCHEMY_DATABASE_URI)}
    SCHEDULER_TIMEZONE = {"timezone": utc}
