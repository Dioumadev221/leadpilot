from app.config import Settings
from app.crm.base import CRMAdapter, CrmContact, CrmError, CrmResult


def get_crm(settings: Settings, session_factory) -> CRMAdapter:
    if settings.crm_provider == "hubspot":
        from app.crm.hubspot import HubSpotAdapter

        return HubSpotAdapter(settings.hubspot_token)
    if settings.crm_provider == "zoho":
        from app.crm.zoho import ZohoAdapter

        return ZohoAdapter(settings.zoho_client_id, settings.zoho_client_secret,
                           settings.zoho_refresh_token, settings.zoho_dc)
    from app.crm.mock import MockCrmAdapter

    return MockCrmAdapter(session_factory)


__all__ = ["CRMAdapter", "CrmContact", "CrmError", "CrmResult", "get_crm"]
