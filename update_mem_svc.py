import re

with open("cloudguard/infra/memory_service.py", "r") as f:
    code = f.read()

# Add raw_drift to VictorySummary
code = re.sub(
    r'(fix_parameters: dict\[str, Any\] = field\(default_factory=dict\))',
    r'\1\n    raw_drift: dict[str, Any] = field(default_factory=dict)',
    code
)

# Update to_semantic_document
new_to_semantic_document = """    def to_semantic_document(self) -> str:
        \"\"\"
        Convert to a *sanitized* embedding document via the Semantic Stripper.
        \"\"\"
        if self.raw_drift:
            return sanitize_for_embedding(self.raw_drift)
            
        resource_type = self.resource_type or _anonymize_resource_id(self.resource_id)
        return (
            f"drift_type={self.drift_type} "
            f"resource_type={resource_type} "
            f"remediation_action={self.remediation_action} "
            f"remediation_tier={self.remediation_tier} "
            f"environment={self.environment}"
        )"""
code = re.sub(r'    def to_semantic_document.*?environment}=\{self\.environment\}"\n        \)', new_to_semantic_document, code, flags=re.DOTALL)

# Update query_victory
old_query_text = """        query_text = (
            f"drift_type={drift_type} "
            f"resource_type={resource_type}"
        )
        # Note: raw_logs are intentionally NOT appended to the query
        # text — they are infrastructure noise that would dilute the
        # semantic signal. The drift_type + resource_type pair is the
        # minimal "Security DNA" signature for H-MEM lookup."""

new_query_text = """        # If raw logs are available, use the Semantic Stripper to build a highly accurate similarity query
        if raw_logs and len(raw_logs) > 0:
            try:
                import json
                drift_dict = json.loads(raw_logs[0])
                query_text = sanitize_for_embedding(drift_dict)
            except Exception:
                query_text = f"drift_type={drift_type} resource_type={resource_type}"
        else:
            query_text = f"drift_type={drift_type} resource_type={resource_type}"
"""
code = code.replace(old_query_text, new_query_text)

with open("cloudguard/infra/memory_service.py", "w") as f:
    f.write(code)

