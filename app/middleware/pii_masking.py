import re
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Configure logger for audit purposes
logger = logging.getLogger("pii_audit_logger")
logger.setLevel(logging.INFO)

class PIIMaskingMiddleware(BaseHTTPMiddleware):
    """
    Lightweight PII Masking Middleware for the Gateway.
    Intercepts incoming requests and anonymizes sensitive information 
    (Emails, Phone Numbers, HKIDs, Account Numbers) before they reach the LLM.
    Logs masking actions for audit purposes without recording the actual PII.
    """
    def __init__(self, app):
        super().__init__(app)
        # Pre-compile regex patterns for lightweight, fast execution
        self.patterns = {
            "EMAIL": re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
            "HKID": re.compile(r'[A-Z]{1,2}\d{6}\(?[0-9A]\)?'),
            "PHONE": re.compile(r'(?:\+?852\s?)?[569]\d{3}\s?\d{4}|\b\d{8,15}\b'),
            "ACCOUNT_NUMBER": re.compile(r'\b\d{10,12}\b'), # Standard account length
        }

    def mask_text(self, text: str) -> tuple[str, dict]:
        """Masks PII in a given string and returns the masked string and an audit summary."""
        audit_counts = {key: 0 for key in self.patterns.keys()}
        masked_text = text

        for pii_type, pattern in self.patterns.items():
            def repl(match):
                audit_counts[pii_type] += 1
                return f"[REDACTED_{pii_type}]"
            
            masked_text = pattern.sub(repl, masked_text)

        return masked_text, audit_counts

    async def dispatch(self, request: Request, call_next) -> Response:
        # Intercept POST, PUT, PATCH methods which carry payload
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    body_json = json.loads(body.decode('utf-8'))
                    total_audit = {key: 0 for key in self.patterns.keys()}
                    total_audit["NAME"] = 0
                    
                    # Recursively traverse and mask strings in the JSON payload
                    def traverse_and_mask(data):
                        if isinstance(data, str):
                            masked, counts = self.mask_text(data)
                            for k, v in counts.items():
                                total_audit[k] += v
                            return masked
                        elif isinstance(data, dict):
                            new_dict = {}
                            sensitive_keys = {"user_name", "first_name", "last_name", "full_name", "client_name", "customer_name"}
                            for k, v in data.items():
                                if k.lower() in sensitive_keys and isinstance(v, str):
                                    new_dict[k] = "[REDACTED_NAME]"
                                    total_audit["NAME"] += 1
                                else:
                                    new_dict[k] = traverse_and_mask(v)
                            return new_dict
                        elif isinstance(data, list):
                            return [traverse_and_mask(item) for item in data]
                        return data

                    masked_body_json = traverse_and_mask(body_json)
                    
                    # If any PII was masked, log it securely for audit (NO raw PII included)
                    if any(v > 0 for v in total_audit.values()):
                        user_id = request.headers.get("X-User-ID", "unknown_user")
                        audit_log = {
                            "event_type": "pii_masked",
                            "user_id": user_id,
                            "path": request.url.path,
                            "summary": total_audit
                        }
                        logger.info(f"AUDIT LOG: {json.dumps(audit_log)}")
                    
                    # Reconstruct the request with the masked body
                    masked_body_bytes = json.dumps(masked_body_json).encode('utf-8')
                    
                    # Replace the request body stream and the cached body
                    async def receive():
                        return {"type": "http.request", "body": masked_body_bytes}
                    
                    request._receive = receive
                    if hasattr(request, "_body"):
                        request._body = masked_body_bytes

                    
            except json.JSONDecodeError:
                # If it's not JSON, skip masking for now (or implement raw text masking if needed)
                pass

        # Proceed with the modified request
        response = await call_next(request)
        return response
