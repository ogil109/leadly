from datetime import datetime, timedelta
import requests
from flask import current_app, abort
from flask_login import login_user
from .models import Token, TokenRefreshJob, AuthRequest
from . import db


# Function to create HubSpot auth URL
def get_hubspot_auth_url():
    current_app.logger.info('Generating HubSpot auth URL...')
    try:
        try:
            new_auth_request = AuthRequest()
            db.session.add(new_auth_request)
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error when creating new auth request: {e}")
            db.session.rollback()

        params = {
            'client_id': current_app.config['HUBSPOT_CLIENT_ID'],
            'redirect_uri': current_app.config['HUBSPOT_REDIRECT_URI'],
            'scope': current_app.config['HUBSPOT_SCOPES'],
            'state': new_auth_request.state_uuid
        }

        url = f"{current_app.config['HUBSPOT_AUTH_URL']}?client_id={params['client_id']}&redirect_uri={params['redirect_uri']}&scope={params['scope']}&state={params['state']}"
        current_app.logger.info(f'Generated HubSpot auth URL: {url}')
        return url
    except Exception as e:
        current_app.logger.error(f"Error in get_hubspot_auth_url function: {e}")
        abort(500, description="Error building OAuth client URL")

# Function to get token from authorization code and refresh it perpetually
def get_token_from_code(code, user_id):
    current_app.logger.info(f'Fetching token for code: {code} and user ID: {user_id}')
    
    try:
        headers = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'}
        data = {
            'grant_type': 'authorization_code',
            'client_id': current_app.config['HUBSPOT_CLIENT_ID'],
            'client_secret': current_app.config['HUBSPOT_CLIENT_SECRET'],
            'redirect_uri': current_app.config['HUBSPOT_REDIRECT_URI'],
            'code': code
        }

        response = requests.post(current_app.config['HUBSPOT_TOKEN_URL'], headers=headers, data=data)
        response_json = response.json()

        if response.status_code != 200:
            current_app.logger.error(f"Error in get_token_from_code function: {response_json}")
            abort(500, description="Couldn't fetch token from HubSpot")

        token = Token(
            user_id=user_id,
            access_token=response_json['access_token'],
            refresh_token=response_json['refresh_token'],
            token_type=response_json['token_type'],
            expires_in=response_json['expires_in'],
            expires_at=datetime.utcnow() + timedelta(seconds=response_json['expires_in'])
        )

        db.session.add(token)
        if not token in db.session:
            current_app.logger.error("Failed to add token to the session.")
            abort(500, description="Database error")
        db.session.commit()
        current_app.logger.info(f'Token fetched and saved for user ID: {user_id}')

        # Flask user login
        login_user(token)
        current_app.logger.info(f'Successfully logged in user: {user_id}')
    
    except Exception as e:
        current_app.logger.error(f"Error while saving token: {e}")
        db.session.rollback()  # Rollback in case of errors to maintain the session's integrity
        abort(500, description="Error saving token")

    try:    
        # Schedule or reschedule the automatic refresh job for this token
        refresh_job = TokenRefreshJob.get_by_token(user_id)

        if not refresh_job:
            refresh_job = TokenRefreshJob(token=user_id)
            db.session.add(refresh_job)
            db.session.flush()  # Flush here allows the refresh_job to be persisted temporarily to call its methods without committing
            refresh_job.create_job(token)
        else:
            refresh_job.reschedule_job(token.expires_at - timedelta(minutes=5))

        db.session.commit()

    except Exception as e:
        current_app.logger.error(f"Error while scheduling token refresh job: {e}")
        db.session.rollback()  # Rollback in case of errors to maintain the session's integrity
        abort(500, description="Error scheduling refresh job")