"""
The `oauth` module handles the OAuth authentication process for interacting with the HubSpot API.

It contains functions for generating the HubSpot authentication URL, handling the OAuth callback,
and retrieving and saving access tokens.

This module relies on the `Token` and `TokenRefreshJob` models defined in the `models` module.

Functions:
- `get_hubspot_auth_url()`: Generates the HubSpot authentication URL for initiating the OAuth flow.
- `oauth_callback()`: Callback route for handling the OAuth callback from HubSpot.
- `get_token_from_code(code, request_id)`: Retrieves the access token from HubSpot using the authorization code.
- `save_token(request_id, response_json)`: Saves the retrieved access token to the database.
"""

from typing import Any

import requests
from flask import abort, current_app
from flask_login import login_user

from leadly import db
from leadly.oauth.models import Token, TokenRefreshJob


# Function to create HubSpot auth URL
def get_hubspot_auth_url() -> tuple[str, Any | str] | None:
    """
    Generate a HubSpot authentication URL.

    Returns:
        str: The generated authentication URL.
        int: The ID of the authentication request.
    """
    current_app.logger.info("Generating HubSpot auth URL...")

    try:
        # Create a new empty Token object with request_id and state_uuid
        new_request = Token()
        db.session.add(new_request)
        db.session.commit()

        current_app.logger.info(
            f"Created new auth request with request_id: {new_request.request_id} and state_uuid: {new_request.state_uuid}"
        )
    except Exception as e:
        current_app.logger.error(f"Error when creating new auth request: {e}")
        db.session.rollback()
        abort(500, description="Error creating new auth request")

    # Build auth URL
    params = {
        "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
        "redirect_uri": current_app.config["HUBSPOT_REDIRECT_URI"],
        "scope": current_app.config["HUBSPOT_SCOPES"],
        "state": new_request.state_uuid,
    }

    url = f"{current_app.config['HUBSPOT_AUTH_URL']}?client_id={params['client_id']}&redirect_uri={params['redirect_uri']}&scope={params['scope']}&state={params['state']}"
    current_app.logger.info(f"Generated HubSpot auth URL: {url}")

    # Return tuple with URL and request_id
    return url, new_request.request_id


# Function to get token data from handed authorization code
def get_token_from_code(code, request_id) -> None:
    current_app.logger.info(f"Fetching token with request: {request_id} using code: {code}")

    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
        data = {
            "grant_type": "authorization_code",
            "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
            "client_secret": current_app.config["HUBSPOT_CLIENT_SECRET"],
            "redirect_uri": current_app.config["HUBSPOT_REDIRECT_URI"],
            "code": code,
        }

        # POST request to HubSpot token endpoint to retrieve JSON response with full token data
        response = requests.post(
            current_app.config["HUBSPOT_TOKEN_URL"], headers=headers, data=data
        )
        response_json = response.json()

        if response.status_code != 200:
            current_app.logger.error(f"Error in get_token_from_code function: {response_json}")
            abort(500, description="Couldn't fetch token from HubSpot")

        # Save token to database updating empty Token instance
        save_token(request_id, response_json)

    except Exception as e:
        current_app.logger.error(f"Error while saving token: {e}")
        db.session.rollback()  # Rollback in case of errors to maintain the session's integrity
        abort(500, description="Error saving token")


# Function to save the fetched token data and create and store corresponding refresh job
def save_token(request_id, response_json) -> None:
    """
    - Saves the token details for a given request updating previously created empty Token instance.
    - Logs user in.
    - Schedules an APScheduler job for automatic token refresh.

    Parameters:
        request_id (str): The ID of the request.
        response_json (dict): The JSON response containing the token details.

    Returns:
        None

    Raises:
        HTTPException: If there is an error saving the token.
    """
    try:
        current_app.logger.info(f"Saving token details for request: {request_id}")

        # Inserting token details from JSON response into previously created Token instance
        token = Token.get_by_request(request_id)
        token.update_token_details(response_json)

        # Flask user login
        login_user(token)

        current_app.logger.info(f"Flask successfully logged in request: {request_id}")

        # Schedule automatic refresh job for this token
        TokenRefreshJob.create_or_reschedule_job(token)

    except Exception as e:
        current_app.logger.error(f"Error while saving token: {e}")
        db.session.rollback()  # Backup rollback (called methods also rollback if errors)
        abort(500, description="Error saving token")
