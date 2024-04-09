import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
from flask import current_app
from pymysql import IntegrityError, OperationalError
from requests.exceptions import Timeout

from leadly import db, scheduler


# Generate UUID function
def generate_uuid() -> str:
    return str(uuid.uuid4())


# Token model to store OAuth tokens
class Token(db.Model):
    request_id = db.Column(db.String(36), primary_key=True, unique=True)
    state_uuid = db.Column(db.String(36), unique=True, nullable=False)
    access_token = db.Column(db.String(300))
    refresh_token = db.Column(db.String(300))
    expires_in = db.Column(db.Integer)
    expires_at = db.Column(db.DateTime)

    # Request ID and state UUID init
    def __init__(self) -> None:
        super().__init__()
        self.request_id = generate_uuid()
        self.state_uuid = generate_uuid()

    # Class method to avoid database query
    @classmethod
    def get_by_request(cls, request_id) -> Any | None:
        """
        Retrieve a Token object from the database by its request ID.

        Args:
            request_id (str): The request ID of the token.

        Returns:
            Token: The Token object with the matching request ID, or None if not found.
        """
        return cls.query.filter_by(request_id=request_id).first()

    # Class method to avoid database query
    @classmethod
    def get_by_state(cls, state) -> Any | None:
        """
        Retrieve a Token object from the database by its state UUID.

        Args:
            state (str): The state UUID of the token.

        Returns:
            Token: The Token object with the matching state UUID, or None if not found.
        """
        return cls.query.filter_by(state_uuid=state).first()

    # Required Flask-Login method, sets request_id as the user ID
    def get_id(self) -> str:
        return self.request_id

    # Required Flask-Login method, True if there is a Token with expires_at in the future
    @property
    def is_authenticated(self) -> bool:
        # Ensure expires_at is not None and there's an access token
        if not self.expires_at or not self.access_token:
            return False
        # Will return true if expires_at is in the future
        return datetime.utcnow() < self.expires_at

    # Required Flask-Login method, True if the Token expires in 5 minutes or more
    @property
    def is_active(self) -> bool:
        # Ensure expires_at is not None and there's an access token
        if not self.expires_at or not self.access_token:
            return False
        # Will return true if expires_at is in the future with a 5 minute buffer
        return datetime.utcnow() < self.expires_at - timedelta(minutes=5)

    # Required Flask-Login method
    @property
    def is_anonymous(self):
        return False

    # Refresh logic
    @classmethod
    def refresh(cls, request_id) -> None:
        current_app.logger.info(f"Starting token refresh for request: {request_id}")
        token = cls.get_by_request(request_id)
        if not token:
            current_app.logger.error(f"No Token found for request: {request_id}")
            return
        if token._is_refresh_needed():
            # Fetch the refreshed token JSON data from HubSpot via POST request
            refreshed_token_data = token._fetch_refreshed_token()

            # Check for JSON retrieved data before calling update_token_details
            if refreshed_token_data:
                token.update_token_details(refreshed_token_data)
            else:
                current_app.logger.error("Failed to refresh the token. No data received.")
        current_app.logger.info(f"Finished token refresh for request: {request_id}")

    # Check if a refresh is needed, returning true if current time is inside buffering window
    def _is_refresh_needed(self) -> bool:
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)

    # Fetch the refreshed token from HubSpot and return a JSON object with the data
    def _fetch_refreshed_token(self) -> Optional[Dict[str, Any]]:
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
            data = {
                "grant_type": "refresh_token",
                "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
                "client_secret": current_app.config["HUBSPOT_CLIENT_SECRET"],
                "refresh_token": self.refresh_token,
            }

            response = requests.post(
                current_app.config["HUBSPOT_TOKEN_URL"],
                headers=headers,
                data=data,
                timeout=10,
            )
            response.raise_for_status()
            response_json = response.json()

            return response_json
        except Timeout as e:
            current_app.logger.error(f"Timeout error at POST request: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            current_app.logger.error(f"HTTP error: {e}")
            return None

    # Update token in database (either after refreshing or the first time fetched) with JSON data
    def update_token_details(self, token_data) -> None:
        current_app.logger.info(
            f"Token details about to be saved/updated for request: {self.request_id}"
        )

        # Update token details
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]
        self.expires_in = token_data["expires_in"]
        self.expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])

        # Commit the changes to the database
        try:
            db.session.add(self)
            db.session.commit()
        except OperationalError as e:
            current_app.logger.error(f"Operational Error in update_token_details: {e}")
            db.session.rollback()
        except IntegrityError as e:
            current_app.logger.error(f"Integrity Error in update_token_details: {e}")
            db.session.rollback()

        current_app.logger.info(f"Token details saved/updated for request: {self.request_id}")

    # Fetch token instance by request_id and remove it to logout
    @classmethod
    def remove_by_request(cls, request_id) -> bool:
        """
        Remove the token associated with the given request ID.

        Parameters:
            request_id (int): The ID of the request.

        Returns:
            bool: True if the token was successfully removed, False otherwise.
        """

        instance = cls.get_by_request(request_id)
        if not instance:
            current_app.logger.error(f"No Token found for request ID: {request_id}")
            return False

        try:
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(f"Successfully removed token for request ID: {request_id}")
            return True
        except OperationalError as e:
            current_app.logger.error(f"Operational Error in remove_by_request: {e}")
            db.session.rollback()
            return False
        except IntegrityError as e:
            current_app.logger.error(f"Integrity Error in remove_by_request: {e}")
            db.session.rollback()
            return False


# Model to manage scheduled jobs for token refresh
class TokenRefreshJob(db.Model):
    job_id = db.Column(db.String(36), primary_key=True)
    token_request_id = db.Column(db.String(36), db.ForeignKey("token.request_id"), unique=True)
    next_run_time = db.Column(db.DateTime)

    def __init__(self, job_id, token_request_id, next_run_time) -> None:
        super().__init__()
        self.job_id = job_id
        self.token_request_id = token_request_id
        self.next_run_time = next_run_time

    # Class method to fetch job associated to a token request id in database
    @classmethod
    def get_by_request(cls, request_id) -> Any | None:
        """
        Get the refresh job associated with a token request ID.

        Parameters:
            request_id: token_request_id (foreign key to token.request_id).

        Returns:
            instance: The refresh job associated with the token request ID, or None if not found.
        """
        return cls.query.filter_by(token_request_id=request_id).first()

    # Method to fetch seconds until next refresh for a filtered token
    def seconds_until_refresh(self) -> int | None:
        """
        Calculates seconds until the next refresh for the given TokenRefreshJob instance.

        Returns:
            int | None: The number of seconds until the next refresh, or None if an error occurs.

        Raises:
            ValueError: If the refresh job is not found or the next run time is not found.

        """

        current_app.logger.info(
            f"Calculating seconds until next refresh for request: {self.token_request_id}"
        )

        try:
            refresh_job = TokenRefreshJob.get_by_request(self.token_request_id)
            if not refresh_job:
                raise ValueError("Job not found")

            if not refresh_job.next_run_time:
                raise ValueError("Next run time not found")

            # Calculate the time difference using the stored next_run_time
            time_left = self.next_run_time - datetime.utcnow()
            return time_left.total_seconds()

        except ValueError as e:
            current_app.logger.error(f"Error in seconds_until_refresh: {e}")
            return None

    @classmethod
    def create_or_reschedule_job(cls, token) -> None:
        """
        Create or reschedule a job for token refresh.

        If a refresh job does not exist for the token's request ID, a new job is created using the
        `_create_job` method. If a job already exists, it is rescheduled using the `_reschedule_job`
        method with the new expiration time of the token (token.expires_at - timedelta(minutes=5)).

        Parameters:
            token: Token object containing the information to create or reschedule the job for.

            The entire object must be passed to this function given that, it will:

            - Create a new job if no job exists for the token's request ID (and all its parameters).
            - Reschedule an existing job if a job already exists for the token's request ID.

        Returns:
            None
        """
        refresh_job = cls.get_by_request(token.request_id)

        # If no job exists, instantiate class via _create_job. If job exists, reschedule it
        if not refresh_job:
            cls._create_job(token)
        else:
            refresh_job._reschedule_job(token.expires_at - timedelta(minutes=5))

    # APScheduler job creation logic
    @classmethod
    def _create_job(cls, token) -> None:
        """
        Create a job to refresh the token before it expires.

        Parameters:
            token (Token): The token object which will be refreshed via the job.

        Returns:
            None

        Raises:
            OperationalError: If there is an operational error.
            IntegrityError: If there is an integrity error.
        """

        try:
            # Instantiate TokenRefreshJob and save to database
            refresh_job = TokenRefreshJob(
                job_id=generate_uuid(),
                token_request_id=token.request_id,
                next_run_time=token.expires_at - timedelta(minutes=5),
            )

            db.session.add(refresh_job)
            db.session.commit()

            current_app.logger.info(
                f"Creating job with ID: {refresh_job.job_id} for request: {token.request_id}"
            )

            # Add job to APScheduler persistent job store
            with scheduler.app.app_context():
                scheduler.add_job(
                    id=refresh_job.job_id,
                    func=token.refresh,
                    trigger="date",
                    run_date=refresh_job.next_run_time,
                    args=[token.request_id],
                )
                current_app.logger.info(
                    f"Refresh job created with ID: {refresh_job.job_id} for request: {token.request_id}"
                )

                # Commit changes to database
                db.session.commit()
        except OperationalError as e:
            current_app.logger.error(f"Operational Error in _create_job: {e}")
            db.session.rollback()
        except IntegrityError as e:
            current_app.logger.error(f"Integrity Error in _create_job: {e}")
            db.session.rollback()

    def _reschedule_job(self, new_run_time) -> None:
        # Update job instance with new run time and commit to database
        self.next_run_time = new_run_time

        db.session.add(self)
        db.session.commit()

        # APScheduler job rescheduling with new run time
        with scheduler.app.app_context():
            scheduler.reschedule_job(self.job_id, trigger="date", run_date=new_run_time)
            current_app.logger.info(
                f"Refresh job rescheduled with ID: {self.job_id} for new run time: {new_run_time}"
            )

    # Removing token refresh job by request_id to logout
    @classmethod
    def remove_by_request(cls, request_id) -> bool:
        current_app.logger.info(f"Removing job for request: {request_id}")
        instance = cls.get_by_request(request_id)
        if not instance:
            current_app.logger.error(f"No TokenRefreshJob object found for request: {request_id}")
            return False

        try:
            # Removing APScheduler job
            with scheduler.app.app_context():
                scheduler.remove_job(instance.job_id)

            # Delete instance of TokenRefreshJob
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(
                f"Successfully removed job with ID: {instance.job_id} for request: {request_id}"
            )
            return True
        except OperationalError as e:
            current_app.logger.error(f"Operational Error in remove_by_request: {e}")
            db.session.rollback()
            return False
        except IntegrityError as e:
            current_app.logger.error(f"Integrity Error in remove_by_request: {e}")
            db.session.rollback()
            return False
