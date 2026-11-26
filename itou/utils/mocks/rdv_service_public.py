# Responses of RDV Service Public: Doorkeeper for /oauth/token, RDV-Solidarités blueprints for /api/v1/

RDV_SERVICE_PUBLIC_TOKEN_BODY = {
    "access_token": "access-token",
    "token_type": "Bearer",
    "expires_in": 7200,
    "refresh_token": "refresh-token",
    "scope": "write",
    "created_at": 1762938000,
}

RDV_SERVICE_PUBLIC_AGENT_BODY = {
    "agent": {
        "id": 42,
        "first_name": "Alice",
        "last_name": "Martin",
        "email": "alice.martin@example.com",
    },
}

RDV_SERVICE_PUBLIC_RDV_PLAN_BODY = {
    "rdv_plan": {
        "id": 1234,
        "user_id": 5678,
        "created_at": "2026-11-12T10:00:00.000+01:00",
        "updated_at": "2026-11-12T10:00:00.000+01:00",
        "url": "https://rdv-service-public.fake/agents/rdv_plans/1234",
        "rdv": None,
    },
}
