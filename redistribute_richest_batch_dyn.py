#!/usr/bin/env python3
"""
Batch version with dynamic destination count: pick richest subaddress,
reserve 0.001 XMR for fee, then determine max destinations (capped at 16)
such that each gets >= 0.001 XMR.
"""

import requests, json, sys, argparse, random, time
from datetime import datetime, timezone

MIN_UNLOCKED = 1000000000  # 0.001 XMR in atomic units
DELAY = 120  # 2 minutes
MAX_DEST = 15

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class DynBatchLoop:
    def __init__(self, wallet_url="http://192.168.1.188:28088"):
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

    def run(self, delay=DELAY):
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*80}")
            print(f"Batch iteration {iteration} — {ts()}")
            print(f"{'='*80}")

            subs = self.get_all_subs()
            if not subs:
                print("  No subaddresses found")
                time.sleep(delay)
                continue

            batch_size = sum(1 for s in subs if s["unlocked"] >= MIN_UNLOCKED)
            if batch_size == 0:
                print("  No subaddresses with >= 0.001 XMR unlocked")
                time.sleep(delay)
                continue

            sent_in_batch = 0
            print(f"  Batch size: {batch_size} (subs with unlocked >= {self.fmt(MIN_UNLOCKED):.12f})")

            for tx_idx in range(batch_size):
                subs.sort(key=lambda s: s["unlocked"], reverse=True)
                richest = subs[0]

                if richest["unlocked"] == 0:
                    print("  Richest has 0 unlocked — ending batch")
                    break

                remaining = richest["unlocked"] - MIN_UNLOCKED
                if remaining <= 0:
                    print(f"    Richest (a={richest['account']}, s={richest['subaddr']}) "
                          f"unlocked={self.fmt(richest['unlocked']):.12f} — "
                          f"not enough for fee, skipping")
                    richest["unlocked"] = 0
                    continue

                pool = [s for s in subs if s["address"] and s["address"] != richest["address"]]
                if not pool:
                    print(f"    No other subaddresses available, skipping")
                    richest["unlocked"] = 0
                    continue

                num_dest = min(MAX_DEST, len(pool))
                while num_dest > 0:
                    per_dest = remaining // (num_dest + 1)
                    if per_dest >= MIN_UNLOCKED:
                        break
                    num_dest -= 1

                if num_dest == 0:
                    print(f"    Richest (a={richest['account']}, s={richest['subaddr']}) "
                          f"remaining={self.fmt(remaining):.12f} — "
                          f"cannot split with >= 0.001 per dest, skipping")
                    richest["unlocked"] = 0
                    continue

                dests = random.sample(pool, num_dest)
                per_dest = remaining // (num_dest + 1)

                print(f"\n  TX {tx_idx+1}/{batch_size}")
                print(f"    Richest: account={richest['account']}, subaddr={richest['subaddr']}, "
                      f"unlocked={self.fmt(richest['unlocked']):.12f}, "
                      f"fee_reserve={self.fmt(MIN_UNLOCKED):.12f}")
                print(f"    Destinations: {num_dest}, per dest: {self.fmt(per_dest):.12f}")

                params = {
                    "destinations": [{"amount": per_dest, "address": d["address"]} for d in dests],
                    "account_index": richest["account"],
                    "subaddr_indices": [richest["subaddr"]],
                    "priority": 0,
                }

                err, result = self.rpc_raw("transfer", params)
                if err:
                    print(f"    FAILED: {err}")
                    richest["unlocked"] = 0
                    continue

                print(f"    SUCCESS")
                print(f"      TX: {result.get('tx_hash', '?')}")
                print(f"      Amount: {self.fmt(result.get('amount', 0)):.12f}")
                print(f"      Fee: {self.fmt(result.get('fee', 0)):.12f}")

                sent_amount = result.get('amount', 0)
                for s in subs:
                    if s["account"] == richest["account"] and s["subaddr"] == richest["subaddr"]:
                        s["unlocked"] -= sent_amount
                        break
                sent_in_batch += 1

            print(f"\n  Sent {sent_in_batch}/{batch_size} tx(s) this batch")
            print(f"  Sleeping {delay}s...")
            time.sleep(delay)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://192.168.1.188:28088")
    p.add_argument("--delay", type=int, default=DELAY)
    args = p.parse_args()
    try:
        DynBatchLoop(args.wallet_url).run(delay=args.delay)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(0)
