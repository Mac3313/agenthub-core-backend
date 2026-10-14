import os
import httpx
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet

class VaultSettings(BaseSettings):
    slack_client_id: str = Field(..., validation_alias="SLACK_CLIENT_ID")
    slack_client_secret: str = Field(..., validation_alias="SLACK_CLIENT_SECRET")
    slack_redirect_uri: str = Field(..., validation_alias="SLACK_REDIRECT_URI")
    encryption_key: str = Field(..., validation_alias="VAULT_ENCRYPTION_KEY")
    slack_scopes: str = "commands,app_mentions:read,chat:write"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

try:
    settings = VaultSettings()
    fernet_cipher = Fernet(settings.encryption_key.encode())
except Exception as config_error:
    raise RuntimeError(f"System Configuration Refused: Invalid or missing environmental nodes: {config_error}")

app = FastAPI(
    title="Slack OAuth Async Token Vault Service",
    description="Securing multi-tenant access credentials via runtime cryptographic wrappers."
)

class SecuredTenantPayload(BaseModel):
    team_id: str = Field(..., examples=["T01ABC23XYZ"])
    team_name: str = Field(..., examples=["Acme Corp"])
    encrypted_bot_token: str = Field(..., description="Symmetrically encrypted bot token ready for storage layer ingestion.")

@app.get("/api/v1/auth/slack/authorize", tags=["Cryptographic OAuth Pipeline"])
async def initiate_slack_handshake():
    target_installation_url = (
        f"https://slack.com"
        f"?client_id={settings.slack_client_id}"
        f"&scope={settings.slack_scopes}"
        f"&redirect_uri={settings.slack_redirect_uri}"
    )
    return RedirectResponse(url=target_installation_url)

@app.get("/api/v1/auth/slack/callback", response_model=SecuredTenantPayload, tags=["Cryptographic OAuth Pipeline"])
async def handle_slack_oauth_callback(
    code: str = Query(..., description="Ephemeral access code parsed from Slack redirection handshake")
):
    async with httpx.AsyncClient() as client:
        try:
            exchange_response = await client.post(
                "https://slack.com",
                data={
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                    "code": code,
                    "redirect_uri": settings.slack_redirect_uri
                },
                timeout=10.0
            )
            data = exchange_response.json()
            
            if not data.get("ok"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Slack Authorization Engine Rejected Exchange: {data.get('error', 'Unknown Error Node')}"
                )
            
            raw_bot_token = data.get("access_token")
            if not raw_bot_token:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Malformed OAuth response signature: Missing access_token endpoint array."
                )
                
            encrypted_bytes = fernet_cipher.encrypt(raw_bot_token.encode())
            
            return SecuredTenantPayload(
                team_id=data["team"]["id"],
                team_name=data["team"]["name"],
                encrypted_bot_token=encrypted_bytes.decode()
            )
            
        except httpx.RequestError as network_exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Critical network transit interruption during upstream OAuth call: {network_exception}"
            )
