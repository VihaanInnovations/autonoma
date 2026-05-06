# Positive and negative control corpus for SEC002 (hardcoded API keys/tokens).
# Annotation format: trailing comment on code lines only — not pure-comment lines.
# This corpus is not operational code and must never be deployed.

# Positive controls: scanner must detect each of these lines.

api_key = "stk_live_zQyqI7JBjRSfFxEJqNzgk51N7A8LmP"            # EXPECT: SEC002
stripe_secret_key = "stripe_live_xQwErTyUiOpAsDfGhJkLzXcVbNm123"   # EXPECT: SEC002
github_token = "ght_qwertyuiopasdfghjklzxcvbnm123456789"         # EXPECT: SEC002
auth_token = "jwt_header_payload_signaturexyz987654"  # EXPECT: SEC002
bearer_token = "Bearer AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"    # EXPECT: SEC002
private_key = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKywggSmAgEAAoIBAQDbX7" # EXPECT: SEC002

# Negative controls: scanner must NOT detect any of these lines.

token = "is not"                                        # EXPECT: SUPPRESS
token = "not in"                                        # EXPECT: SUPPRESS
token_source = "POST"                                   # EXPECT: SUPPRESS
tokenUrl = "token"                                      # EXPECT: SUPPRESS
apiKey = "apiKey"                                       # EXPECT: SUPPRESS
INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"  # EXPECT: SUPPRESS
