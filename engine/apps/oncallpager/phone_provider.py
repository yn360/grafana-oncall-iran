import logging
from random import randint

import requests

from apps.base.utils import live_settings
from apps.phone_notifications.exceptions import (
    FailedToMakeCall,
    FailedToSendSMS,
    FailedToStartVerification,
)
from apps.phone_notifications.phone_provider import PhoneProvider, ProviderFlags
from django.core.cache import cache

from apps.alerts.models import AlertGroup

logger = logging.getLogger(__name__)


class OncallPagerPhoneProvider(PhoneProvider):
    """Phone provider that forwards calls/SMS to the oncall-pager server."""

    def __init__(self):
        self.server_url = getattr(live_settings, "ONCALL_PAGER_SERVER_URL", "").rstrip("/")
        self.timeout_seconds = getattr(live_settings, "ONCALL_PAGER_TIMEOUT_SECONDS", 10)

    def _post(self, path: str, payload: dict) -> dict:
        if not self.server_url:
            raise ValueError("ONCALL_PAGER_SERVER_URL is empty")
        response = requests.post(
            f"{self.server_url}{path}",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    def make_notification_call(self, number: str, text: str, alert_group: AlertGroup):
        params = {
            "alertgroup_id": str(alert_group.public_primary_key),
            "receiver": number,
            "message": text,
        }
        try:
            response = self._post("/make_notification_call", params)
            logger.info(f"OncallPager.make_call: {response}")
        except Exception as e:
            logger.error(f"OncallPager.make_call: failed {e}")
            raise FailedToMakeCall

    def send_verification_sms(self, number: str):
        # generating random code
        code = str(randint(100000, 999999))
        # cache the code
        cache.set(self._cache_key(number), code, timeout=10 * 60)
        params = {
            "receiver": number,
            "code": code,
        }
        try:
            response = self._post("/send_verification_sms", params)
            logger.info(f"OncallPager.send_verification_sms: {response}")
        except Exception as e:
            logger.error(f"OncallPager.send_verification_sms: failed {e}")
            raise FailedToStartVerification

    def finish_verification(self, number: str, code: str):
        """compare and checking users entered verification code with cached code"""
        has = cache.get(self._cache_key(number))
        if has is not None and has == code:
            return number
        else:
            return None

    def _cache_key(self, number):
        return f"oncall_pager_{number}"

    @property
    def flags(self) -> ProviderFlags:
        """specifies available features of this provider"""
        return ProviderFlags(
            configured=bool(self.server_url),
            test_sms=True,
            test_call=False,
            verification_call=False,
            verification_sms=True,
        )
