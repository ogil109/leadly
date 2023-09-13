from datetime import datetime, timedelta
import requests
from flask import current_app, abort, session
from flask_login import login_user
from .models import Token, TokenRefreshJob
from .. import db


# Function to create HubSpot auth URL
def get_hubspot_auth_url():
    current_app.logger.info("Generating HubSpot auth URL...")

    try:
        try:
            # Creating new request will init a new request_id and state_uuid
            new_request = Token()
            db.session.add(new_request)
            db.session.commit()

            current_app.logger.info(
                f"Created new auth request with request_id: {new_request.request_id} and state_uuid: {new_request.state_uuid}"
            )
        except Exception as e:
            current_app.logger.error(f"Error when creating new auth request: {e}")
            db.session.rollback()

        params = {
            "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
            "redirect_uri": current_app.config["HUBSPOT_REDIRECT_URI"],
            "scope": current_app.config["HUBSPOT_SCOPES"],
            "state": new_request.state_uuid,
        }

        url = f"{current_app.config['HUBSPOT_AUTH_URL']}?client_id={params['client_id']}&redirect_uri={params['redirect_uri']}&scope={params['scope']}&state={params['state']}"
        current_app.logger.info(f"Generated HubSpot auth URL: {url}")

        # Returning tuple and using request_id to identify Flask Session in /login route
        return url, new_request.request_id
    except Exception as e:
        current_app.logger.error(f"Error in get_hubspot_auth_url function: {e}")
        abort(500, description="Error building OAuth client URL")


# Function to get token from authorization code
def get_token_from_code(code, request_id):
    current_app.logger.info(
        f"Fetching token with request: {request_id} using code: {code}"
    )

    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
        data = {
            "grant_type": "authorization_code",
            "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
            "client_secret": current_app.config["HUBSPOT_CLIENT_SECRET"],
            "redirect_uri": current_app.config["HUBSPOT_REDIRECT_URI"],
            "code": code,
        }

        response = requests.post(
            current_app.config["HUBSPOT_TOKEN_URL"], headers=headers, data=data
        )
        response_json = response.json()

        if response.status_code != 200:
            current_app.logger.error(
                f"Error in get_token_from_code function: {response_json}"
            )
            abort(500, description="Couldn't fetch token from HubSpot")

        # Save token to database
        save_token(request_id, response_json)

    except Exception as e:
        current_app.logger.error(f"Error while saving token: {e}")
        db.session.rollback()  # Rollback in case of errors to maintain the session's integrity
        abort(500, description="Error saving token")


# Function to save the fetched token to database and create and store corresponding refresh job
def save_token(request_id, response_json):
    try:
        current_app.logger.info(f"Updated session data: {session}")
        current_app.logger.info(f"Saving token details for request: {request_id}")

        # Inserting token details from json response
        token = Token.get_by_request(request_id)
        token.update_token_details(response_json)

        # Flask user login
        login_user(token)
        current_app.logger.info(f"Session data: {session}")
        current_app.logger.info(f"Flask successfully logged in request: {request_id}")

        # Schedule automatic refresh job for this token
        TokenRefreshJob.create_or_reschedule_job(token)

    except Exception as e:
        current_app.logger.error(f"Error while saving token: {e}")
        db.session.rollback()  # Rollback in case of errors to maintain the session's integrity
        abort(500, description="Error saving token")
