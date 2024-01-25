import requests
from flask import Blueprint, abort, current_app, jsonify, redirect, request, url_for
from flask_login import current_user, logout_user

from delphi import db
from delphi.oauth.models import Token, TokenRefreshJob
from delphi.oauth.oauth import get_hubspot_auth_url, get_token_from_code

# Create a Blueprint object
oauth = Blueprint("oauth", __name__)


@oauth.route("/")
def index():
    current_app.logger.info("Accessing index route...")
    try:
        current_app.logger.info(f"Current user authentification: {current_user.is_authenticated}")
        current_app.logger.info(f"Current user activity status: {current_user.is_active}")

        # If the user is authenticated, token is active and there's a refresh job, return JSON
        if current_user.is_authenticated:
            # Check if there's an access token and expires at more than buffer time
            if current_user.is_active:
                # Check if the active token has a scheduled refresh job. If not, create one
                job = TokenRefreshJob.get_by_request(current_user.request_id)
                current_app.logger.info(
                    f"Refresh job for request {current_user.request_id}: {job.job_id}"
                )
                if not job:
                    current_app.logger.info(
                        f"No refresh job for request: {current_user.request_id}, creating one..."
                    )
                    TokenRefreshJob.create_or_reschedule_job(
                        Token.get_by_request(current_user.request_id)
                    )

                    # Redefine job if there wasn't one and the if statement was true
                    job = TokenRefreshJob.get_by_request(current_user.request_id)

                seconds_left = job.seconds_until_refresh()

                return jsonify(
                    request_id=current_user.request_id,
                    seconds_until_refresh=int(seconds_left) if seconds_left else None,
                )
            else:
                current_app.logger.info(
                    "Token is not active, redirecting user to log out before requesting another token..."
                )
                return redirect(url_for("oauth.logout"))
        else:
            current_app.logger.info("User not logged in, redirecting to log in...")
            return redirect(url_for("oauth.login"))
    except Exception as e:
        current_app.logger.error(f"Error in index function: {e}")
        abort(500)


@oauth.route("/login")
def login():
    current_app.logger.info("Accessing login route...")
    try:
        # Check if user entered route by accident and is already active
        if current_user.is_active:
            return redirect(url_for("oauth.index"))

        # Create new request if there's no existing session and mark session with request_id
        auth_url, request_id = get_hubspot_auth_url()
        current_app.logger.info("Redirecting to HubSpot auth URL...")

        # Send user to new request auth url
        return redirect(auth_url)

    except Exception as e:
        current_app.logger.error(f"Error in login function: {e}")
        abort(500)


@oauth.route("/oauth-callback/")
def oauth_callback():
    """
    Handle the OAuth callback route.

    This function is responsible for handling the '/oauth-callback/' route when the user is redirected after granting access to HubSpot.

    - It fetches the state parameter from the request arguments and logs the received state.
    - The function fetches the (empty) token associated with the received state to prevent CSRF attacks.
    - If the token is not found, it logs an error and aborts the request with a 500 status code.
    - Otherwise, it retrieves the code from the request arguments.
    - The function calls the 'get_token_from_code' passing the code and the stored token's request ID.

    Finally, after retrieving full token data, saving it to db and creating APScheduler refresh job (handed by 'get_token_from_code' function), user is redirected to index.

    Raises:
        requests.RequestException: If there is a network error.
        Exception: If there is any other error.

    Returns:
        None
    """
    current_app.logger.info("Accessing oauth-callback route...")
    current_app.logger.info(f"Full callback URL: {request.url}")
    try:
        fetched_state = request.args.get("state")
        current_app.logger.info(f"Received state: {fetched_state}")

        # Fetching empty token object associated with received state to prevent CSFR
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

        # Retrieve handed code
        code = request.args.get("code")
        current_app.logger.info(f"Received code: {code}")

        # Use code to get token data
        get_token_from_code(code, stored_token.request_id)

        return redirect(url_for("oauth.index"))
    except requests.RequestException as re:
        current_app.logger.error(f"Network error in oauth_callback function: {re}")
        db.session.rollback()
        abort(503, description="Service Unavailable")
    except Exception as e:
        current_app.logger.error(f"Error in oauth_callback function: {e}")
        db.session.rollback()
        abort(500, description="Internal Server Error")


@oauth.route("/logout")
def logout():
    try:
        current_app.logger.info(f"Logging out user with request_id: {current_user.request_id}")

        # Remove associated refresh job, if any
        if TokenRefreshJob.get_by_request(current_user.request_id):
            if not TokenRefreshJob.remove_by_request(current_user.request_id):
                current_app.logger.error(
                    f"Failed to remove token refresh job associated to request: {current_user.request_id}"
                )
            current_app.logger.info(f"Refresh job removed for request: {current_user.request_id}")
        else:
            current_app.logger.info(
                f"No token refresh job associated to request: {current_user.request_id}"
            )

        # Remove token
        if not Token.remove_by_request(current_user.request_id):
            current_app.logger.error(
                f"Failed to remove token with request id: {current_user.request_id}"
            )

        # Flask-Login logout
        if current_user.is_authenticated:
            logout_user()

        return redirect(url_for("oauth.index"))
    except Exception as e:
        current_app.logger.error(f"Error in logout function: {e}")
        abort(500, description="Error during logout")
