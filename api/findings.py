"""
FINDINGS API — ES-FREE VERSION
================================
Returns realistic mock security findings.
Elasticsearch has been removed; no external DB required.
"""
from fastapi import APIRouter

router = APIRouter()

MOCK_FINDINGS = [
    {
        "resource_id": "s3-bucket-prod-assets",
        "resource_type": "S3",
        "title": "S3 Bucket Publicly Accessible",
        "severity": "CRITICAL",
        "risk_score": 95,
        "region": "us-east-1",
        "description": "S3 bucket prod-assets has public read access enabled.",
        "remediation": "Enable 'Block Public Access' on the bucket.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "iam-root-account",
        "resource_type": "IAM",
        "title": "Root Account MFA Disabled",
        "severity": "CRITICAL",
        "risk_score": 92,
        "region": "global",
        "description": "AWS root account does not have MFA enabled.",
        "remediation": "Enable MFA on the root account immediately.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "sg-0a1b2c3d4e5f",
        "resource_type": "EC2",
        "title": "Security Group Open to World",
        "severity": "CRITICAL",
        "risk_score": 88,
        "region": "us-east-1",
        "description": "Security group allows inbound 0.0.0.0/0 on port 22 (SSH).",
        "remediation": "Update Security Group to restrict SSH to corporate CIDR.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "rds-prod-mysql-01",
        "resource_type": "RDS",
        "title": "RDS Publicly Accessible",
        "severity": "HIGH",
        "risk_score": 82,
        "region": "us-east-1",
        "description": "RDS instance is configured with PubliclyAccessible=true.",
        "remediation": "Restrict RDS access and place instance in private subnet.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "cloudtrail-main",
        "resource_type": "CloudTrail",
        "title": "CloudTrail Not Enabled",
        "severity": "HIGH",
        "risk_score": 79,
        "region": "us-east-1",
        "description": "CloudTrail logging is disabled in us-east-1.",
        "remediation": "Enable CloudTrail with multi-region logging.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "vpc-flow-logs-main",
        "resource_type": "VPC",
        "title": "VPC Flow Logs Disabled",
        "severity": "HIGH",
        "risk_score": 74,
        "region": "us-east-1",
        "description": "VPC flow logs are not enabled — no network traffic audit trail.",
        "remediation": "Enable VPC Flow Logs to CloudWatch Logs.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "s3-bucket-logs",
        "resource_type": "S3",
        "title": "S3 Bucket No Encryption",
        "severity": "HIGH",
        "risk_score": 70,
        "region": "us-east-1",
        "description": "S3 bucket logs does not have server-side encryption enabled.",
        "remediation": "Enable encryption using AES-256 or AWS-KMS.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "iam-policy-dev-full",
        "resource_type": "IAM",
        "title": "IAM Password Policy Weak",
        "severity": "HIGH",
        "risk_score": 68,
        "region": "global",
        "description": "IAM password policy does not require minimum length or complexity.",
        "remediation": "Update IAM Policy to require 14+ chars, uppercase, numbers, symbols.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "ec2-i-0abc123def456",
        "resource_type": "EC2",
        "title": "EC2 Instance with Public IP & Open Ports",
        "severity": "MEDIUM",
        "risk_score": 55,
        "region": "us-east-1",
        "description": "EC2 instance has public IP and open ports 80, 443, 8080.",
        "remediation": "Place behind load balancer and remove direct public exposure.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "kms-key-cmk-01",
        "resource_type": "KMS",
        "title": "KMS Key Rotation Disabled",
        "severity": "MEDIUM",
        "risk_score": 50,
        "region": "us-east-1",
        "description": "Customer-managed KMS key does not have annual rotation enabled.",
        "remediation": "Rotate KMS Key — enable automatic key rotation.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
    {
        "resource_id": "ebs-snap-00ab11cd22",
        "resource_type": "EBS",
        "title": "EBS Snapshot Public",
        "severity": "HIGH",
        "risk_score": 77,
        "region": "us-east-1",
        "description": "EBS snapshot is shared publicly and visible to all AWS accounts.",
        "remediation": "Modify snapshot permissions to private.",
        "detected_at": "2026-04-14T05:00:00Z",
    },
]

# Idle EC2 instances for cost-waste endpoint
MOCK_EC2_IDLE = [
    {
        "resource_id": "ec2-i-idle-001",
        "resource_type": "EC2",
        "instance_type": "m5.xlarge",
        "region": "us-east-1",
        "cpu_avg": 1.8,
        "running_hours": 720,
        "monthly_cost": 185.0,
        "estimated_waste": 166.5,
        "remediation": "Terminate or rightsize to t3.micro",
    },
    {
        "resource_id": "ec2-i-idle-002",
        "resource_type": "EC2",
        "instance_type": "c5.2xlarge",
        "region": "us-west-2",
        "cpu_avg": 2.3,
        "running_hours": 720,
        "monthly_cost": 310.0,
        "estimated_waste": 279.0,
        "remediation": "Rightsize to c5.large or use Spot instances",
    },
    {
        "resource_id": "ec2-i-idle-003",
        "resource_type": "EC2",
        "instance_type": "r5.large",
        "region": "us-east-1",
        "cpu_avg": 3.1,
        "running_hours": 720,
        "monthly_cost": 182.0,
        "estimated_waste": 145.6,
        "remediation": "Rightsize to t3.medium",
    },
]


@router.get("/summary")
def get_findings_summary():
    by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in MOCK_FINDINGS:
        sev = f.get("severity", "LOW")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    total = sum(by_severity.values())
    return {
        "critical": by_severity["CRITICAL"],
        "high": by_severity["HIGH"],
        "medium": by_severity["MEDIUM"],
        "low": by_severity["LOW"],
        "total": total,
        "chart_data": [
            {"name": "Critical", "value": by_severity["CRITICAL"], "color": "#ef4444"},
            {"name": "High",     "value": by_severity["HIGH"],     "color": "#f97316"},
            {"name": "Medium",   "value": by_severity["MEDIUM"],   "color": "#eab308"},
            {"name": "Low",      "value": by_severity["LOW"],      "color": "#22c55e"},
        ],
    }


@router.get("/critical")
def get_critical():
    return [f for f in MOCK_FINDINGS if f["severity"] == "CRITICAL"]


@router.get("/top")
def get_top(limit: int = 10):
    sorted_findings = sorted(MOCK_FINDINGS, key=lambda x: x["risk_score"], reverse=True)
    return sorted_findings[:limit]


@router.get("/by-type")
def by_resource_type():
    counts: dict = {}
    for f in MOCK_FINDINGS:
        rt = f.get("resource_type", "Unknown")
        counts[rt] = counts.get(rt, 0) + 1
    return [{"key": k, "doc_count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


@router.get("/cost-waste")
def get_cost_waste():
    total_waste = sum(i["estimated_waste"] for i in MOCK_EC2_IDLE)
    total_cost  = sum(i["monthly_cost"]    for i in MOCK_EC2_IDLE)
    savings_rate = round(total_waste / total_cost * 100) if total_cost > 0 else 0
    return {
        "items":        MOCK_EC2_IDLE,
        "total_waste":  round(total_waste, 2),
        "annual_waste": round(total_waste * 12, 2),
        "idle_count":   len(MOCK_EC2_IDLE),
        "savings_rate": savings_rate,
        "total_cost":   round(total_cost, 2),
    }