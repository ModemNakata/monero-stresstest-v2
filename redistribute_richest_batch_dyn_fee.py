#!/usr/bin/env python3
"""
Batch version with dynamic fee retry for Monero FCMP++ Stressnet testing.
Fixed to dynamically pool all generated subaddresses, preventing 72-tx loops.
"""

import requests
import json
import sys
import argparse
import random
import time
from datetime import datetime, timezone

FEE_RESERVE = 500000000   # 0.0005 XMR — base fee reserve
FEE_STEP = 500000000      # 0.0005 XMR — added per retry
MAX_FEE_RETRIES = 5
MIN_SOURCE = 1500000000    # 0.0015 XMR — minimum unlocked to be a source
MIN_DEST = 100000000       # 0.0001 XMR — minimum per-destination amount
DELAY = 0                  # Maintained at 0 as requested
MAX_DEST = 15

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class DynFeeBatchLoop:
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
        """Fetches subaddresses that have a balance history (Sources)."""
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

    def get_all_destinations(self):
        """Fetches ALL generated subaddresses regardless of balance (Destinations)."""
        accs = self.rpc("get_accounts", {}).get("subaddress_accounts", [])
        dests = []
        for acc in accs:
            aidx = acc["account_index"]
            r = self.rpc("get_address", {"account_index": aidx})
            if r is None:
                continue
            for addr_info in r.get("addresses", []):
                dests.append({
                    "account": aidx,
                    "subaddr": addr_info["address_index"],
                    "address": addr_info["address"]
                })
        return dests

    def run(self, delay=DELAY):
        iteration = 0
        
        # Load the destination pool once globally to save RPC overhead
        all_destinations = self.get_all_destinations()
        print(f"Loaded {len(all_destinations)} total destination addresses from the wallet.")

        while True:
            iteration += 1
            print(f"\n{'='*80}")
            print(f"Batch iteration {iteration} — {ts()}")
            print(f"{'='*80}")
            
            subs = self.get_all_subs()
            if not subs:
                print("  No subaddresses found with balance history")
                time.sleep(delay)
                continue

            batch_size = sum(1 for s in subs if s["unlocked"] >= MIN_SOURCE)
            if batch_size == 0:
                print(f"  No subaddresses with >= {self.fmt(MIN_SOURCE):.12f} XMR unlocked. (Waiting for locktimes...)")
                time.sleep(5)  # Short defensive sleep to avoid CPU thrashing when locked
                continue

            sent_in_batch = 0
            print(f"  Batch size: {batch_size} (subs with unlocked >= {self.fmt(MIN_SOURCE):.12f})")
            
            for tx_idx in range(batch_size):
                subs.sort(key=lambda s: s["unlocked"], reverse=True)
                richest = subs[0]
                if richest["unlocked"] == 0:
                    print("  Richest has 0 unlocked — ending batch")
                    break

                fee_reserve = FEE_RESERVE
                tx_ok = False
                
                for attempt in range(MAX_FEE_RETRIES + 1):
                    remaining = richest["unlocked"] - fee_reserve
                    if remaining <= 0:
                        if attempt == 0:
                            print(f"    Richest (a={richest['account']}, s={richest['subaddr']}) "
                                  f"unlocked={self.fmt(richest['unlocked']):.12f} — "
                                  f"not enough for fee, skipping")
                        else:
                            print(f"    Attempt {attempt+1}/{MAX_FEE_RETRIES+1}: "
                                  f"fee_reserve={self.fmt(fee_reserve):.12f} > unlocked, "
                                  f"giving up")
                        break

                    # FIX: Draw from the full list of 1000+ addresses, not just funded ones
                    pool = [d for d in all_destinations if d["address"] and d["address"] != richest["address"]]
                    if not pool:
                        print(f"    No other subaddresses available in total pool, skipping")
                        break

                    num_dest = min(MAX_DEST, len(pool))
                    while num_dest > 0:
                        per_dest = remaining // (num_dest + 1)
                        if per_dest >= MIN_DEST:
                            break
                        num_dest -= 1

                    if num_dest == 0:
                        print(f"    Richest (a={richest['account']}, s={richest['subaddr']}) "
                              f"remaining={self.fmt(remaining):.12f} — "
                              f"cannot split with >= {self.fmt(MIN_DEST)} per dest, skipping")
                        break

                    dests = random.sample(pool, num_dest)
                    per_dest = remaining // (num_dest + 1)
                    
                    print(f"\n  TX {tx_idx+1}/{batch_size} (attempt {attempt+1}/{MAX_FEE_RETRIES+1})")
                    print(f"    Richest: account={richest['account']}, subaddr={richest['subaddr']}, "
                          f"unlocked={self.fmt(richest['unlocked']):.12f}, "
                          f"fee_reserve={self.fmt(fee_reserve):.12f}")
                    print(f"    Destinations: {num_dest}, per dest: {self.fmt(per_dest):.12f}")
                    print(f"    Dests: " + ", ".join(f"[{d['account']},{d['subaddr']}]" for d in dests))

                    params = {
                        "destinations": [{"amount": per_dest, "address": d["address"]} for d in dests],
                        "account_index": richest["account"],
                        "subaddr_indices": [richest["subaddr"]],
                        "priority": 0,
                    }
                    
                    err, result = self.rpc_raw("transfer", params)
                    if err:
                        print(f"    FAILED: {err}")
                        if "Transaction would be too large" in err:
                            print(f"    -> Too large, retrying with transfer_split")
                            err2, result2 = self.rpc_raw("transfer_split", params)
                            if err2:
                                print(f"    transfer_split also FAILED: {err2}")
                                fee_reserve += FEE_STEP
                                continue
                            print(f"    SUCCESS (via transfer_split)")
                            print(f"      TXs: {result2.get('tx_hash_list', [])}")
                            amounts = result2.get('amount_list', [0])
                            fees = result2.get('fee_list', [0])
                            print(f"      Amounts: {[self.fmt(a) for a in amounts]}")
                            print(f"      Fees: {[self.fmt(f) for f in fees]}")
                            sent_amount = sum(amounts)
                            for s in subs:
                                if s["account"] == richest["account"] and s["subaddr"] == richest["subaddr"]:
                                    s["unlocked"] -= sent_amount
                                    break
                            sent_in_batch += 1
                            tx_ok = True
                            break
                        fee_reserve += FEE_STEP
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
                    tx_ok = True
                    break

                if not tx_ok:
                    richest["unlocked"] = 0

            print(f"\n  Sent {sent_in_batch}/{batch_size} tx(s) this batch")
            print(f"  Sleeping {delay}s...")
            time.sleep(delay)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://192.168.1.188:28088")
    p.add_argument("--delay", type=int, default=DELAY)
    args = p.parse_args()
    
    try:
        DynFeeBatchLoop(args.wallet_url).run(delay=args.delay)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(0)
