import re

with open("cloudguard/simulator/inject_drift.py", "r") as f:
    content = f.read()

# add chaos to parser choices
content = content.replace('choices=["single", "proactive"]', 'choices=["single", "proactive", "chaos"]')
content = content.replace('help="\'single\' injects one drift; \'proactive\' runs the 20-tick Amber sequence"', 'help="\'single\' injects one drift; \'proactive\' runs Amber sequence; \'chaos\' triggers Phase 8 stress test"')

# add arguments
args_to_add = """    parser.add_argument("--count", type=int, default=50, help="Number of simultaneous drifts to inject (Default: 50)")
    parser.add_argument("--chaos-factor", type=float, default=1.0, help="Chaos factor")
    parser.add_argument("--resource-conflict-target", default="iam-role-PII-vault", help="Resource ID to force a collision")
"""
content = re.sub(r'(parser\.add_argument\("--type", default="OIDC_TRUST_BREACH",)', args_to_add + r'\1', content)

# update __main__ logic
main_logic_replacement = """    if args.mode == "chaos":
        asyncio.run(
            inject_chaos(
                count=args.count,
                conflict_target=args.resource_conflict_target,
                verbose=args.verbose,
            )
        )
    elif args.mode == "proactive":"""
content = content.replace('    if args.mode == "proactive":', main_logic_replacement)

with open("cloudguard/simulator/inject_drift.py", "w") as f:
    f.write(content)
