import os
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


class Config:
    # Flask and db config
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = True  # Set to True if using HTTPS
    SESSION_COOKIE_SAMESITE = 'Lax'

    # HubSpot configurations
    HUBSPOT_AUTH_URL = 'https://app-eu1.hubspot.com/oauth/authorize'
    HUBSPOT_TOKEN_URL = 'https://api.hubapi.com/oauth/v1/token'
    HUBSPOT_CLIENT_ID = os.environ.get('HUBSPOT_CLIENT_ID')
    HUBSPOT_CLIENT_SECRET = os.environ.get('HUBSPOT_CLIENT_SECRET')
    HUBSPOT_REDIRECT_URI = os.environ.get('HUBSPOT_REDIRECT_URI')
    HUBSPOT_SCOPES = 'crm.objects.contacts.read%20crm.objects.companies.read%20crm.objects.companies.write%20crm.objects.deals.read'

    # APScheduler config
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {
        'default': SQLAlchemyJobStore(url=SQLALCHEMY_DATABASE_URI)
    }