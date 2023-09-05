import uuid
from datetime import datetime, timedelta
import requests
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .. import db, scheduler


# Token model to store OAuth tokens (users) and handle token refresh via APScheduler
class Token(db.Model):
    user_id = db.Column(db.String(36), primary_key=True, unique=True) # Will be assigned from AuthRequest
    access_token = db.Column(db.String(300))
    refresh_token = db.Column(db.String(300))
    token_type = db.Column(db.String(32))
    expires_in = db.Column(db.Integer)
    expires_at = db.Column(db.DateTime)

    # Flask-Login user required properties
    def get_id(self):
        return self.user_id

    @property
    def is_authenticated(self):
        return self.access_token and datetime.utcnow() < self.expires_at

    @property
    def is_active(self):
        return datetime.utcnow() < self.expires_at

    @property
    def is_anonymous(self):
        return False

    @classmethod
    def refresh(cls, user_id):
        current_app.logger.info(f'Starting token refresh for user ID: {user_id}')
        token = cls.query.get(user_id)
        if not token:
            current_app.logger.error(f"No Token found for user ID: {user_id}")
            return
        if token._is_refresh_needed():
            refreshed_token_data = token._fetch_refreshed_token()
            if refreshed_token_data:
                token._update_token_details(refreshed_token_data)
            else:
                current_app.logger.error("Failed to refresh the token. No data received.")
        current_app.logger.info(f'Finished token refresh for user ID: {user_id}')

    # Check if a refresh is needed based on the expiration time
    def _is_refresh_needed(self):
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)

    # Fetch the refreshed token from HubSpot
    def _fetch_refreshed_token(self):
        try:
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'
            }
            data = {
                'grant_type': 'refresh_token',
                'client_id': current_app.config['HUBSPOT_CLIENT_ID'],
                'client_secret': current_app.config['HUBSPOT_CLIENT_SECRET'],
                'refresh_token': self.refresh_token
            }

            response = requests.post(current_app.config['HUBSPOT_TOKEN_URL'], headers=headers, data=data)
            response_json = response.json()

            if response.status_code != 200:
                current_app.logger.error(f"Error in refresh_token function: {response_json}")
                return None

            return response_json
        except Exception as e:
            current_app.logger.error(f"Error in refresh_token function: {e}")
            return None

    # Update token in database
    def _update_token_details(self, token_data):
        self.access_token = token_data['access_token']
        self.refresh_token = token_data['refresh_token']
        self.token_type = token_data['token_type']
        self.expires_in = token_data['expires_in']
        self.expires_at = datetime.utcnow() + timedelta(seconds=token_data['expires_in'])
        
        # Commit the changes to the database
        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error in _update_token_details when committing to the database: {e}")
            db.session.rollback()

    # Removing token by user_id to logout
    @classmethod
    def remove_by_user_id(cls, user_id):
        instance = cls.query.get(user_id)
        if not instance:
            current_app.logger.error(f"No Token found for user ID: {user_id}")
            return False
        
        try:
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(f"Successfully removed token for user ID: {user_id}")
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in remove_by_user_id for Token: {e}")
            return False


# Model to manage scheduled jobs for token refresh
class TokenRefreshJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(36), db.ForeignKey('token.user_id'), unique=True)
    job_id = db.Column(db.String(36))
    next_run_time = db.Column(db.DateTime)

    # Static method to generate UUID
    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())

    # Class method to avoid database logic in instantiation
    @classmethod
    def get_by_token(cls, token):
        return cls.query.filter_by(token=token).first()

    # Class method to fetch seconds until next refresh for a filtered token
    @classmethod
    def seconds_until_refresh(cls, token_id):
        current_app.logger.info(f'Calculating seconds until next refresh for token: {token_id}')
        refresh_job = cls.get_by_token(token_id)
        
        if not refresh_job or not refresh_job.next_run_time:
            current_app.logger.error(f"Job or next run time not found for token: {token_id}")
            return None

        # Calculate the time difference using the stored next_run_time
        time_left = refresh_job.next_run_time - datetime.utcnow()
        return time_left.total_seconds()

    def create_job(self, token):
        current_app.logger.info(f'Starting refresh job creation for token: {token.user_id}')
        try:
            self.job_id = TokenRefreshJob.generate_uuid()

            # Scheduling next run according to expiry time and adding a 5 minute buffer
            self.next_run_time = token.expires_at - timedelta(minutes=5)
            job = current_app.scheduler.add_job(id=self.job_id, func=token.refresh, trigger="date", run_date=self.next_run_time, args=[token.user_id])

            db.session.commit()
            current_app.logger.info(f'Job with ID {self.job_id} created successfully for token: {token.user_id}')
            return job
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in create_job: {e}")

    def reschedule_job(self, new_run_time):
        if self.job_id:
            current_app.scheduler.reschedule_job(self.job_id, trigger="date", run_date=new_run_time)

    # Removing token refresh job by user_id to logout
    @classmethod
    def remove_by_token(cls, user_id):
        current_app.logger.info(f'Removing job for user ID: {user_id}')
        instance = cls.get_by_token(user_id)
        if not instance:
            current_app.logger.error(f"No TokenRefreshJob object found for user ID: {user_id}")
            return False
        
        try:
            current_app.scheduler.remove_job(instance.job_id)
            db.session.delete(instance)
            db.session.commit()
            current_app.logger.info(f"Successfully removed job with ID: {instance.job_id}")
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in remove_by_user_id for TokenRefreshJob: {e}")
            return False


# Model to store Auth Request UUID and create User ID to handle it to Token
class AuthRequest(db.Model):
    state_uuid = db.Column(db.String(36), unique=True, nullable=False, primary_key=True)
    user_id = db.Column(db.String(36), unique=True, nullable=False)

    # Static method to generate UUID
    @staticmethod
    def generate_uuid():
        return str(uuid.uuid4())

    # Automatic UUID generation and assignation on every instance
    def __init__(self, *args, **kwargs):
        super(AuthRequest, self).__init__(*args, **kwargs)
        self.state_uuid = self.generate_uuid()
        self.user_id = self.generate_uuid()

    # Class method to avoid database logic in instantiation
    @classmethod
    def get_by_state_uuid(cls, state_uuid):
        return cls.query.get(state_uuid)