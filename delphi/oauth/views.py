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
                # Check if the active token has a scheduled refresh job. If not, log out user
                job = TokenRefreshJob.get_by_request(current_user.request_id)
                if not job or job.next_run_time >= datetime.utcnow():
                    return redirect(url_for("main.logout"))

                seconds_left = TokenRefreshJob.seconds_until_refresh(
                    current_user.request_id
                )

                return jsonify(
                    request_id=current_user.request_id,
                    seconds_until_refresh=int(seconds_left) if seconds_left else None,
                )
            else:
                current_app.logger.info(
                    "Token is not active, redirecting user to log out before requesting another token..."
                )
                return redirect(url_for("main.logout"))
        else:
            current_app.logger.info("User not logged in, redirecting to log in...")
            return redirect(url_for("main.login"))
    except Exception as e:
        current_app.logger.error(f"Error in index function: {e}")
        abort(500)


@main.route("/login")
def login():
    current_app.logger.info("Accessing login route...")
    try:
        # Check if user entered route by accident and is already active
        if current_user.is_authenticated and current_user.is_active:
            return redirect(url_for("main.index"))

        # Check if there's an active session within time (in case of app restart)
        if "request_id" in session:
            current_app.logger.info(f"Session already exists: {session}")
            stored_token = Token.get_by_request(session["request_id"])

            # Clear session data and log again if associated token can't be found
            if not stored_token:
                current_app.logger.info(
                    f"Couldn't find stored token for request: {session['request_id']}"
                )
                session.clear()
                current_app.logger.info(
                    "Session was cleared, initiating new request..."
                )

            # Logout user if stored token is expired
            """
            Conditions needed:
                - App restarted
                - User has old session['request_id']
                - User has a token tied to old session['request_id']
                - The token is expired and can't be refreshed
                - User entered login route directly (avoiding main route previous check)
            """
            if stored_token and not stored_token.is_active:
                current_app.logger.info("Associated token expired, logging out...")
                return redirect(url_for("main.logout"))

            # If the token is still active and has a scheduled refresh job in the future, log the user in
            if stored_token and stored_token.is_active:
                job = TokenRefreshJob.get_by_request(stored_token.request_id)
                if job and job.next_run_time > datetime.utcnow():
                    login_user(stored_token)
                    current_app.logger.info("User relogged with session data")
                    return redirect(url_for("main.index"))
                else:
                    # If no refresh job in the future, logout and generate new request
                    return redirect(url_for("main.logout"))

        # Create new request if there's no existing session and mark session with request_id
        auth_url, request_id = get_hubspot_auth_url()
        session["request_id"] = request_id
        current_app.logger.info(f"Updated session data: {session}")
        current_app.logger.info("Redirecting to HubSpot auth URL...")
        return redirect(auth_url)

    except Exception as e:
        current_app.logger.error(f"Error in login function: {e}")
        abort(500)


@main.route("/oauth-callback/")
def oauth_callback():
    current_app.logger.info(f"Session data: {session}")
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

        current_app.logger.info(
            f"Stored associated token found with state: {stored_token.state_uuid}"
        )
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
        """
        Session request id is used to erase TokenRefreshJob and Token in
        case user is not logged in but has an expired token tied to an
        old session['request_id']
        """
        current_app.logger.info(
            f"Logging out user with request_id: {session['request_id']}"
        )

        # Remove associated refresh job, if any
        """
        Checking for existence of refresh job to avoid error while removing it in case of:
            - App restarted
            - User has old session['request_id']
            - User has a token tied to old session['request_id']
            - The token is still active
            - The token does not have associated refresh job
            - Login route redirects to logout route but no refresh job can be deleted
        """

        if TokenRefreshJob.get_by_request(session["request_id"]):
            if not TokenRefreshJob.remove_by_request(session["request_id"]):
                current_app.logger.error(
                    f"Failed to remove token refresh job associated to request: {session['request_id']}"
                )
        else:
            current_app.logger.info(
                f"No token refresh job associated to request: {session['request_id']}"
            )

        # Remove token
        if not Token.remove_by_request(session["request_id"]):
            current_app.logger.error(
                f"Failed to remove token with request id: {session['request_id']}"
            )

        # Flask logout (if user is logged in)
        if current_user.is_authenticated:
            logout_user()

        # Clear session data
        session.clear()

        return redirect(url_for("main.index"))
    except Exception as e:
        current_app.logger.error(f"Error in logout function: {e}")
        abort(500, description="Error during logout")
