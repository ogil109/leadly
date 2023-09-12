import requests
from datetime import datetime, timedelta
from flask import (
    Flask,
    jsonify,
    redirect,
    url_for,
    request,
    current_app,
    abort,
    Blueprint,
    session,
)
from flask_login import current_user, login_user, logout_user
from .models import Token, TokenRefreshJob
from .oauth import get_hubspot_auth_url, get_token_from_code
from .. import db


# Create a Blueprint object
main = Blueprint("main", __name__)


@main.route("/")
def index():
    current_app.logger.info("Accessing index route...")
    current_app.logger.info(f"Session data: {session}")
    try:
        current_app.logger.info(
            f"Current user authentification: {current_user.is_authenticated}"
        )
        current_app.logger.info(
            f"Current user activity status: {current_user.is_active}"
        )

        # If the user is authenticated and the token is active, return the index
        if current_user.is_authenticated:
            if current_user.is_active:
                seconds_left = TokenRefreshJob.seconds_until_refresh(
                    current_user.request_id
                )

                return jsonify(
                    request_id=current_user.request_id,
                    seconds_until_refresh=int(seconds_left) if seconds_left else None,
                )
            else:
                current_app.logger.info("Token is not active, redirecting to login...")
                return redirect(url_for("main.login"))
        else:
            current_app.logger.info("User not logged in, redirecting...")
            return redirect(url_for("main.login"))
    except Exception as e:
        current_app.logger.error(f"Error in index function: {e}")
        abort(500)


@main.route("/login")
def login():
    current_app.logger.info("Accessing login route...")
    try:
        # If the user is already authenticated and the token is active (and user entered route by accident), redirect to the index
        if current_user.is_authenticated and current_user.is_active:
            return redirect(url_for("main.index"))

        # Check if there's an existing session in the browser
        if "request_id" in session:
            current_app.logger.info("Session already exists")
            stored_token = Token.get_by_request(session["request_id"])

            # Clear session data and log again if token wasn't found or if it's out of buffer time
            if (
                not stored_token
                or stored_token.expires_at - timedelta(minutes=5) <= datetime.utcnow()
            ):
                # Clear session data
                session.clear()

                current_app.logger.info(
                    "Token wasn't found or it's out of buffer time. Session was cleared. Redirecting to login..."
                )
                return redirect(url_for("main.login"))

            # If the token is still active and has a scheduled refresh job, log the user in and redirect to the index
            else:
                if not TokenRefreshJob.get_by_request(stored_token.request_id):
                    # Delete token and redirect to login after clearing session data if no refresh job is found
                    current_app.logger.info("Token has no refresh job, deleting")
                    Token.remove_by_request(stored_token.request_id)
                    session.clear()
                    return redirect(url_for("main.login"))

                login_user(stored_token)
                current_app.logger.info("User logged in with session data")
                return redirect(url_for("main.index"))

        # Create new request if there's no existing session and mark session with request_id
        auth_url, request_id = get_hubspot_auth_url()
        session["request_id"] = request_id
        current_app.logger.info("Redirecting to HubSpot auth URL...")
        return redirect(auth_url)

    except Exception as e:
        current_app.logger.error(f"Error in login function: {e}")
        abort(500)


@main.route("/oauth-callback/")
def oauth_callback():
    current_app.logger.info("Accessing oauth-callback route...")
    current_app.logger.info(f"Full callback URL: {request.url}")
    try:
        fetched_state = request.args.get("state")
        current_app.logger.info(f"Received state: {fetched_state}")

        # Fetching token associated with received state to prevent CSFR
        stored_token = Token.get_by_state(fetched_state)
        if not stored_token:
            current_app.logger.error(
                f"Token not found for state: {fetched_state} in oauth_callback function"
            )
            abort(500, description="Token not found")

        current_app.logger.info(f"Stored associated token found")
        current_app.logger.info("State match confirmed")

        code = request.args.get("code")
        current_app.logger.info(f"Received code: {code}")

        get_token_from_code(code, stored_token.request_id)

        return redirect(url_for("main.index"))
    except requests.RequestException as re:
        current_app.logger.error(f"Network error in oauth_callback function: {re}")
        db.session.rollback()
        abort(503, description="Service Unavailable")
    except Exception as e:
        current_app.logger.error(f"Error in oauth_callback function: {e}")
        db.session.rollback()
        abort(500, description="Internal Server Error")


@main.route("/logout")
def logout():
    try:
        current_app.logger.info(
            f"Logging out user with request_id: {current_user.request_id}"
        )

        if not TokenRefreshJob.remove_by_request(current_user.request_id):
            abort(500, description="Failed to remove TokenRefreshJob")

        if not Token.remove_by_request(current_user.request_id):
            abort(500, description="Failed to remove Token")

        logout_user()

        # Clear session data
        session.clear()

        return redirect(url_for("main.index"))
    except Exception as e:
        current_app.logger.error(f"Error in logout function: {e}")
        abort(500, description="Error during logout")
