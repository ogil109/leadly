import uuid
from datetime import datetime, timedelta
import requests
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .. import db, scheduler


# Token model to store OAuth tokens and handle token refresh via APScheduler
class Token(db.Model):
    request_id = db.Column(db.String(36), primary_key=True, unique=True)
    state_uuid = db.Column(db.String(36), unique=True, nullable=False)
    access_token = db.Column(db.String(300))
    refresh_token = db.Column(db.String(300))
    token_type = db.Column(db.String(32))
    expires_in = db.Column(db.Integer)
    expires_at = db.Column(db.DateTime)

    # Request ID and state UUID init
    def __init__(self, *args, **kwargs):
        super(Token, self).__init__(*args, **kwargs)
        self.request_id = self.generate_uuid()
        self.state_uuid = self.generate_uuid()

    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())

    # Flask-Login user required properties
    def get_id(self):
        return self.request_id

    @property
    def is_authenticated(self):
        return self.access_token and datetime.utcnow() < self.expires_at

    @property
    def is_active(self):
        # Will take into account buffering
        return datetime.utcnow() < self.expires_at - timedelta(minutes=5)

    @property
    def is_anonymous(self):
        return False

    # Refresh logic
    @classmethod
    def refresh(cls, request_id):
        current_app.logger.info(f"Starting token refresh for request: {request_id}")
        token = cls.get_by_request(request_id)
        if not token:
            current_app.logger.error(f"No Token found for request: {request_id}")
            return
        if token._is_refresh_needed():
            refreshed_token_data = token._fetch_refreshed_token()
            if refreshed_token_data:
                token.update_token_details(refreshed_token_data)
            else:
                current_app.logger.error(
                    "Failed to refresh the token. No data received."
                )
        current_app.logger.info(f"Finished token refresh for request: {request_id}")

    # Check if a refresh is needed based on the expiration time plus buffering
    def _is_refresh_needed(self):
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)

    # Fetch the refreshed token from HubSpot
    def _fetch_refreshed_token(self):
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
            }
            data = {
                "grant_type": "refresh_token",
                "client_id": current_app.config["HUBSPOT_CLIENT_ID"],
                "client_secret": current_app.config["HUBSPOT_CLIENT_SECRET"],
                "refresh_token": self.refresh_token,
            }

            response = requests.post(
                current_app.config["HUBSPOT_TOKEN_URL"], headers=headers, data=data
            )
            response_json = response.json()

            if response.status_code != 200:
                current_app.logger.error(
                    f"Error in refresh_token function: {response_json}"
                )
                return None

            return response_json
        except Exception as e:
            current_app.logger.error(f"Error in refresh_token function: {e}")
            return None

    # Update token in database, either after refreshing or the first time fetched
    def update_token_details(self, token_data):
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]
        self.token_type = token_data["token_type"]
        self.expires_in = token_data["expires_in"]
        self.expires_at = datetime.utcnow() + timedelta(
            seconds=token_data["expires_in"]
        )

        # Commit the changes to the database
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(
                f"Error in update_token_details when committing to the database: {e}"
            )
            db.session.rollback()

        current_app.logger.info(
            f"Token details saved/updated for request: {self.request_id}"
        )

    # Removing token by request_id to logout
    @classmethod
    def remove_by_request(cls, request_id):
        instance = cls.query.get(request_id)
        if not instance:
            current_app.logger.error(f"No Token found for token ID: {request_id}")
            return False

        try:
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(
                f"Successfully removed token for token ID: {request_id}"
            )
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in remove_by_request_id for Token: {e}")
            return False

    # Class method to avoid database logic
    @classmethod
    def get_by_request(cls, request_id):
        return cls.query.filter_by(request_id=request_id).first()

    # Class method to avoid database logic
    @classmethod
    def get_by_state(cls, state):
        return cls.query.filter_by(state_uuid=state).first()


# Model to manage scheduled jobs for token refresh
class TokenRefreshJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token_request_id = db.Column(
        db.String(36), db.ForeignKey("token.request_id"), unique=True
    )
    job_id = db.Column(db.String(36))
    next_run_time = db.Column(db.DateTime)

    # Static method to generate UUID
    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())

    # Class method to avoid database logic, it will return the first job found for a request_id
    @classmethod
    def get_by_request(cls, request_id):
        return cls.query.filter_by(token_request_id=request_id).first()

    # Class method to fetch seconds until next refresh for a filtered token
    @classmethod
    def seconds_until_refresh(cls, request_id):
        current_app.logger.info(
            f"Calculating seconds until next refresh for request: {request_id}"
        )
        refresh_job = cls.get_by_request(request_id)

        if not refresh_job or not refresh_job.next_run_time:
            current_app.logger.error(
                f"Job or next run time not found for request: {request_id}"
            )
            return None

        # Calculate the time difference using the stored next_run_time
        time_left = refresh_job.next_run_time - datetime.utcnow()
        return time_left.total_seconds()

    # Main scheduling function
    @classmethod
    def create_or_reschedule_job(cls, token):
        request_id = token.request_id
        refresh_job = cls.get_by_request(request_id)

        # If no job exists, instantiate class via _create_job class method. If job exists, reschedule it
        if not refresh_job:
            cls._create_job(token)
        else:
            refresh_job._reschedule_job(token.expires_at - timedelta(minutes=5))

    # Job creation logic
    @classmethod
    def _create_job(cls, token):
        try:
            job_id = TokenRefreshJob.generate_uuid()
            next_run_time = token.expires_at - timedelta(minutes=5)

            current_app.logger.info(
                f"Creating job with ID: {job_id} for request: {token.request_id}"
            )

            # Add job to APScheduler
            job = current_app.scheduler.add_job(
                id=job_id,
                func=token.refresh,
                trigger="date",
                run_date=next_run_time,
                args=[token.request_id],
            )
            current_app.logger.info(
                f"Refresh job created with ID: {job_id} for request: {token.request_id}"
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in _create_job for TokenRefreshJob: {e}")

    def _reschedule_job(self, new_run_time):
        if self.job_id:
            current_app.scheduler.reschedule_job(
                self.job_id, trigger="date", run_date=new_run_time
            )
            current_app.logger.info(
                f"Refresh job rescheduled with ID: {self.job_id} for new run time: {new_run_time}"
            )

    # Removing token refresh job by request_id to logout
    @classmethod
    def remove_by_request(cls, request_id):
        current_app.logger.info(f"Removing job for request: {request_id}")
        instance = cls.get_by_request(request_id)
        if not instance:
            current_app.logger.error(
                f"No TokenRefreshJob object found for request: {request_id}"
            )
            return False

        try:
            current_app.scheduler.remove_job(instance.job_id)
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(
                f"Successfully removed job with ID: {instance.job_id}"
            )
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error in remove_by_request_id for TokenRefreshJob: {e}"
            )
            return False
