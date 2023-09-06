import requests
from datetime import datetime
from flask import Flask, jsonify, redirect, url_for, request, current_app, abort, Blueprint, session
from flask_login import current_user, logout_user
from .models import Token, TokenRefreshJob
from .oauth import get_hubspot_auth_url, get_token_from_code
from .. import db


# Create a Blueprint object
main = Blueprint('main', __name__)

@main.route('/')
def index():
    current_app.logger.info('Accessing index route...')
    current_app.logger.info(f"Session data: {session}")
    try:
        current_app.logger.info(f"Current user authentification: {current_user.is_authenticated}")
        if current_user.is_authenticated:
            # Calculate the time left until the token expires
            seconds_left = TokenRefreshJob.seconds_until_refresh(current_user.request_id)

            return jsonify(
                request_id=current_user.request_id,
                seconds_until_refresh=int(seconds_left) if seconds_left else None
            )
        else:
            return redirect(url_for('main.login'))
    except Exception as e:
        current_app.logger.error(f"Error in index function: {e}")
        abort(500)

@main.route('/login')
def login():
    current_app.logger.info('Accessing login route...')
    try:
        if current_user.is_authenticated:
            return redirect(url_for('main.index'))
        else:
            auth_url = get_hubspot_auth_url()
            current_app.logger.info("Redirecting to HubSpot auth URL...")
            return redirect(auth_url)
    except Exception as e:
        current_app.logger.error(f"Error in login function: {e}")
        abort(500)

@main.route('/oauth-callback/')
def oauth_callback():
    current_app.logger.info('Accessing oauth-callback route...')
    current_app.logger.info(f"Full callback URL: {request.url}")
    try:
        fetched_state = request.args.get('state')
        current_app.logger.info(f"Received state: {fetched_state}")

        # Fetching token associated with received state
        stored_token = Token.get_by_state(fetched_state)
        current_app.logger.info(f"Stored state: {stored_token.state_uuid}")

        # State comparison check (no need to check vs fetched_state, given prior initialization)
        current_app.logger.info('Checking state arg to prevent CSFR')
        if not stored_token.state_uuid:
            current_app.logger.error("State mismatch error in oauth_callback function")
            abort(500, description="State mismatch error")

        current_app.logger.info('State match confirmed')
        
        code = request.args.get('code')
        current_app.logger.info(f"Received code: {code}")

        get_token_from_code(code, stored_token.request_id)
        current_app.logger.info(f"Token successfully fetched and stored for request: {stored_token.request_id}")

        return redirect(url_for('main.index'))
    except requests.RequestException as re:
        current_app.logger.error(f"Network error in oauth_callback function: {re}")
        db.session.rollback()
        abort(503, description="Service Unavailable")
    except Exception as e:
        current_app.logger.error(f"Error in oauth_callback function: {e}")
        db.session.rollback()
        abort(500, description="Internal Server Error")

@main.route('/logout')
def logout():
    try:
        if not TokenRefreshJob.remove_by_token(current_user.request_id):
            abort(500, description="Failed to remove TokenRefreshJob")
        
        if not Token.remove_by_request_id(current_user.request_id):
            abort(500, description="Failed to remove Token")

        logout_user()
        return redirect(url_for('main.index'))
    except Exception as e:
        current_app.logger.error(f"Error in logout function: {e}")
        abort(500, description="Error during logout")