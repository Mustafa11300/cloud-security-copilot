# debug_timing.py — run from backend/ with: python debug_timing.py
import time
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

results = {}

def section(name):
    class Timer:
        def __enter__(self):
            self.start = time.time()
            print(f"  ⏳ {name}...")
            return self
        def __exit__(self, *args):
            elapsed = round(time.time() - self.start, 2)
            results[name] = elapsed
            status = "🔴" if elapsed > 5 else "🟡" if elapsed > 2 else "🟢"
            print(f"  {status} {name}: {elapsed}s")
    return Timer()

print("\n" + "="*50)
print("CLOUDGUARD LATENCY DIAGNOSTIC")
print("="*50)

# ─── 1. ES Connection ───────────────────────────────
print("\n[1] Elasticsearch Connection")
with section("ES ping"):
    from elastic.client import es
    es.ping()

# ─── 2. ES Read — cloud-resources ───────────────────
print("\n[2] ES Read: cloud-resources (500 docs)")
with section("ES fetch resources"):
    result = es.search(
        index="cloud-resources",
        body={"query": {"match_all": {}}, "size": 500}
    )
    resources = [h["_source"] for h in result["hits"]["hits"]]
    print(f"     → Got {len(resources)} resources")

# ─── 3. ES Read — security-findings ─────────────────
print("\n[3] ES Read: security-findings")
with section("ES fetch findings"):
    r2 = es.search(
        index="security-findings",
        body={"query": {"match_all": {}}, "size": 500}
    )
    print(f"     → Got {len(r2['hits']['hits'])} findings")

# ─── 4. ES Read — scan-history ──────────────────────
print("\n[4] ES Read: scan-history")
with section("ES fetch scan history"):
    r3 = es.search(
        index="scan-history",
        body={"sort": [{"timestamp": "desc"}], "size": 1}
    )
    print(f"     → Got {len(r3['hits']['hits'])} snapshots")

# ─── 5. Rule Engine ─────────────────────────────────
print("\n[5] Rule Engine")
with section("scan_all_resources"):
    from engine.rules import scan_all_resources
    findings_result = scan_all_resources(resources)
    print(f"     → Found {findings_result['total_findings']} findings")

# ─── 6. Scorer ──────────────────────────────────────
print("\n[6] Scorer")
with section("generate_posture_report"):
    from engine.scorer import generate_posture_report
    report = generate_posture_report(resources, findings_result)
    print(f"     → Score: {report['security']['security_score']}")

# ─── 7. ES Write — findings ──────────────────────────
print("\n[7] ES Write: index_findings")
with section("index_findings"):
    from elastic.indexer import index_findings
    index_findings(findings_result["all_findings"])

# ─── 8. ES Write — snapshot ──────────────────────────
print("\n[8] ES Write: index_scan_snapshot")
with section("index_scan_snapshot"):
    from elastic.indexer import index_scan_snapshot
    index_scan_snapshot(report)

# ─── 9. Nova / Bedrock ──────────────────────────────
print("\n[9] Amazon Nova (Bedrock)")
with section("Nova first token"):
    import boto3, json
    bedrock = boto3.client(
        service_name="bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
    )
    response = bedrock.invoke_model(
        modelId="amazon.nova-lite-v1:0",
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": "Reply with one word: ready"}]}],
            "inferenceConfig": {"maxTokens": 10}
        })
    )
    body = json.loads(response["body"].read())
    print(f"     → Response: {body['output']['message']['content'][0]['text']}")

# ─── 10. Full Nova with context (simulates /chat) ────
print("\n[10] Nova with security context (simulates real /chat call)")
with section("Nova full prompt"):
    sample_context = "FINDINGS: 5 critical S3 buckets, 3 open SSH ports, 8 unencrypted RDS instances. Score: 32/100."
    response2 = bedrock.invoke_model(
        modelId="amazon.nova-lite-v1:0",
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": f"Summarize this in 2 sentences: {sample_context}"}]}],
            "inferenceConfig": {"maxTokens": 200, "temperature": 0.3}
        })
    )
    body2 = json.loads(response2["body"].read())
    print(f"     → {body2['output']['message']['content'][0]['text'][:80]}...")

# ─── SUMMARY ────────────────────────────────────────
print("\n" + "="*50)
print("SUMMARY")
print("="*50)
total = sum(results.values())
for name, elapsed in sorted(results.items(), key=lambda x: -x[1]):
    bar = "█" * int(elapsed * 2)
    status = "🔴 SLOW" if elapsed > 5 else "🟡 OK" if elapsed > 1 else "🟢 fast"
    print(f"  {status:12} {elapsed:5.2f}s  {bar}  {name}")
print(f"\n  TOTAL: {total:.2f}s")
print("\n  Anything 🔴 is your bottleneck. Fix that first.")
print("="*50)