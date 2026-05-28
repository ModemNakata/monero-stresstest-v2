#!/usr/bin/env python3
"""
Find all subaddresses across all accounts, pick the 16 poorest as destinations,
pick the 1 richest as source, send its unlocked balance split into 16 via /transfer
with subtract_fee_from_outputs.
"""

import requests, json, sys, argparse, random

class Redistribute:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc(self, method, params=None):
        if params is None:
            params = {}
        try:
            r = self.session.post(self.wallet_url,
                json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=60)
            result = r.json()
            if "error" in result and result["error"] is not None:
                raise Exception(f"RPC Error {result['error']['code']}: {result['error']['message']}")
            return result.get("result", {})
        except Exception as e:
            print(f"  RPC error: {e}")
            return None

    def format_xmr(self, a):
        return a / 1e12

    def run(self):
        print("=" * 80)
        print("REDISTRIBUTE RICHEST -> 16 POOREST SUBADDRESSES")
        print("=" * 80)

        # Step 1: collect all subaddresses across all accounts
        print("\nScanning all accounts and subaddresses...")
        r = self.rpc("get_accounts", {})
        if r is None:
            return
        accs = r.get("subaddress_accounts", [])
        if not accs:
            print("No accounts found!")
            return

        all_subs = []
        for acc in accs:
            aidx = acc["account_index"]
            r = self.rpc("get_balance", {"account_index": aidx})
            if r is None:
                continue
            for sub in r.get("per_subaddress", []):
                all_subs.append({
                    "account": aidx,
                    "subaddr": sub["address_index"],
                    "address": sub.get("address", ""),
                    "unlocked": sub.get("unlocked_balance", 0),
                    "balance": sub.get("balance", 0)
                })

        if not all_subs:
            print("No subaddresses with balance data found!")
            return

        print(f"  Total subaddresses found: {len(all_subs)}")

        # Step 2: sort by unlocked balance
        sorted_subs = sorted(all_subs, key=lambda s: s["unlocked"])

        # Show the list
        print(f"\n{'account':>8} : {'subaddr':>8} : {'unlocked':>20} : {'locked':>20}")
        print("-" * 62)
        for s in sorted_subs:
            locked = s["balance"] - s["unlocked"]
            print(f"{s['account']:>8} : {s['subaddr']:>8} : {s['unlocked']:>20} : {locked:>20}")
        print("-" * 62)

        # Step 3: pick 16 poorest as destinations, 1 richest as source
        poorest = sorted_subs[:15]
        richest = sorted_subs[-1]

        if richest["unlocked"] == 0:
            print("\nRichest subaddress has 0 unlocked — nothing to redistribute!")
            return

        print(f"\nSelected source:")
        print(f"  Account {richest['account']}, subaddress {richest['subaddr']}: "
              f"{self.format_xmr(richest['unlocked']):.12f} XMR unlocked")

        print(f"\nSelected 16 destinations (poorest):")
        for s in poorest:
            print(f"  Account {s['account']}, subaddress {s['subaddr']}: "
                  f"{self.format_xmr(s['unlocked']):.12f} XMR unlocked")

        # Step 4: build transfer
        dest_addrs = [s["address"] for s in poorest if s["address"]]
        # if len(dest_addrs) < 16:
            # print("Not enough destination addresses with valid address data!")
            # return
        dest_addrs = dest_addrs[:16]

        per_dest = richest["unlocked"] // 16
        # per_dest = per_dest - 500000000
        # per_dest = per_dest - 5000000000
        if per_dest == 0:
            print("Amount per destination too small!")
            return

        print(f"\nSending {16} x {self.format_xmr(per_dest):.12f} XMR = "
              f"{self.format_xmr(per_dest * 16):.12f} XMR total")
        print(f"Using subtract_fee_from_outputs on 1 random destination")

        # fee_dest = random.randrange(16)
        params = {
            "destinations": [{"amount": per_dest, "address": a} for a in dest_addrs],
            "account_index": richest["account"],
            "subaddr_indices": [richest["subaddr"]],
            "priority": 0,
        }

        print(f"\nCalling /transfer...")
        result = self.rpc("transfer", params)
        if result is None:
            print("FAILED")
            return

        print(f"SUCCESS")
        print(f"  TX: {result.get('tx_hash', '?')}")
        print(f"  Amount: {self.format_xmr(result.get('amount', 0)):.12f} XMR")
        print(f"  Fee: {self.format_xmr(result.get('fee', 0)):.12f} XMR")
        print(f"  Weight: {result.get('weight', '?')}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://127.0.0.1:28088")
    args = p.parse_args()
    Redistribute(args.wallet_url).run()
