def extract_identity(claims: dict, client_id: str) -> dict | None:
    """Map Keycloak userinfo/token claims to the internal identity shape.

    Roles live under resource_access.<client_id>.roles for a client-scoped
    check, rather than the realm-wide roles every user gets by default.
    """
    user_id = claims.get("sub")
    if not user_id:
        return None

    roles = claims.get("resource_access", {}).get(client_id, {}).get("roles", [])
    return {
        "user_id": user_id,
        "email": claims.get("email", ""),
        "first_name": claims.get("given_name", ""),
        "last_name": claims.get("family_name", ""),
        "roles": roles,
        "is_admin": "admin" in roles or "realm-admin" in roles,
    }
