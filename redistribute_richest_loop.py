#!/usr/bin/env python3
"""
Loop with 1-minute delay:
  1. Find richest subaddress across all accounts
  2. Pick 15 random subaddresses as destinations
  3. Split richest unlocked by 16, send that amount to each of 15 destinations via /transfer
"""

import requests, json, sys, argparse, random, time
from datetime import datetime, timezone

NUM_DEST = 15
DIVIDE_BY = 16

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class Loop:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc(self, method, params=None):
        if params is None:
            params = {}
        try:
            r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=60)
            result = r.json()
            if "error" in result and result["error"] is not None:
                raise Exception(f"RPC Error {result['error']['code']}: {result['error']['message']}")
            return result.get("result", {})
        except Exception as e:
            return None

    def rpc_raw(self, method, params=None):
        if params is None:
            params = {}
        try:
            r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=60)
            result = r.json()
            if "error" in result and result["error"] is not None:
                e = result["error"]
                return f"RPC Error {e['code']}: {e['message']}", None
            return None, result.get("result", {})
        except Exception as e:
            return str(e), None

    def fmt(self, a):
        return a / 1e12

    def get_all_subs(self):
        accs = self.rpc("get_accounts", {}).get("subaddress_accounts", [])
        subs = []
        for acc in accs:
            aidx = acc["account_index"]
            r = self.rpc("get_balance", {"account_index": aidx})
            if r is None:
                continue
            for sub in r.get("per_subaddress", []):
                subs.append({
                    "account": aidx,
                    "subaddr": sub["address_index"],
                    "address": sub.get("address", ""),
                    "unlocked": sub.get("unlocked_balance", 0),
                    "balance": sub.get("balance", 0)
                })
        return subs

    def run(self, delay=60):
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*80}")
            print(f"Iteration {iteration} — {ts()}")
            print(f"{'='*80}")

            try:
                subs = self.get_all_subs()
                if not subs:
                    print("  No subaddresses found")
                    time.sleep(delay)
                    continue

                # Sort by unlocked descending
                subs.sort(key=lambda s: s["unlocked"], reverse=True)
                richest = subs[0]

                if richest["unlocked"] == 0:
                    print("  Richest subaddress has 0 unlocked")
                    time.sleep(delay)
                    continue

                # Pick 15 random destinations (excluding richest)
                pool = [s for s in subs if s["address"] and s["address"] != richest["address"]]
                if len(pool) < NUM_DEST:
                    print(f"  Not enough subaddresses (need {NUM_DEST}, have {len(pool)})")
                    time.sleep(delay)
                    continue

                dests = random.sample(pool, NUM_DEST)
                per_dest = richest["unlocked"] // DIVIDE_BY

                print(f"  Richest: account={richest['account']}, subaddr={richest['subaddr']}, "
                      f"unlocked={self.fmt(richest['unlocked']):.12f}")
                print(f"  Per dest amount: {self.fmt(per_dest):.12f}")
                print(f"  Destinations: {NUM_DEST} random subaddresses")
                print(f"  Using subtract_fee_from_outputs")

                params = {
                    "destinations": [{"amount": per_dest, "address": d["address"]} for d in dests],
                    "account_index": richest["account"],
                    "subaddr_indices": [richest["subaddr"]],
                    "priority": 0,
                }

                err, result = self.rpc_raw("transfer", params)
                if err:
                    print(f"  FAILED: {err}")
                else:
                    print(f"  SUCCESS")
                    print(f"    TX: {result.get('tx_hash', '?')}")
                    print(f"    Amount: {self.fmt(result.get('amount', 0)):.12f}")
                    print(f"    Fee: {self.fmt(result.get('fee', 0)):.12f}")

            except Exception as e:
                print(f"  EXCEPTION: {e}")

            print(f"  Sleeping {delay}s...")
            time.sleep(delay)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://127.0.0.1:28088")
    p.add_argument("--delay", type=int, default=60*20) # 20 minutes
    args = p.parse_args()
    try:
        Loop(args.wallet_url).run(delay=args.delay)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(0)
