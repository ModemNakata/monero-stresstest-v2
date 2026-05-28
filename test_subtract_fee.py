#!/usr/bin/env python3
"""Test /transfer with subtract_fee_from_outputs — use subaddress with highest unlocked balance."""

import requests, json, sys, argparse

class Test:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc_call(self, method, params=None):
        if params is None:
            params = {}
        payload = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
        try:
            resp = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = resp.json()
            if "error" in result and result["error"] is not None:
                raise Exception(f"RPC Error {result['error']['code']}: {result['error']['message']}")
            return result.get("result", {})
        except Exception as e:
            print(f"    RPC error: {e}")
            return None

    def run(self):
        # Get all per-subaddress balances for account 0
        r = self.rpc_call("get_balance", {"account_index": 0})
        if not r:
            return
        subs = r.get("per_subaddress", [])
        if not subs:
            print("No subaddresses found")
            return

        # Find subaddress with highest unlocked balance
        best = max(subs, key=lambda s: s.get("unlocked_balance", 0))
        src_idx = best["address_index"]
        src_bal = best["unlocked_balance"]
        src_addr = best.get("address", "?")

        print(f"Source: index={src_idx}, unlocked={src_bal} atomic ({src_bal/1e12:.12f} XMR)")

        if src_bal < 1000000000:
            print("Balance too low")
            return

        # Find a different subaddress as destination
        dst = None
        for s in subs:
            if s["address_index"] != src_idx:
                dst = s["address"]
                break
        if not dst:
            # Get any subaddress 1 if not in list
            r2 = self.rpc_call("get_address", {"account_index": 0, "address_index": [1]})
            dst = r2["addresses"][0]["address"] if r2 else None
        if not dst:
            print("No destination")
            return

        amount = src_bal - 5000000
        params = {
            "destinations": [{"amount": amount, "address": dst}],
            "account_index": 0,
            "subaddr_indices": [src_idx],
            "priority": 0,
            "subtract_fee_from_outputs": [0]
        }
        print(f"Sending {amount} atomic with subtract_fee_from_outputs=[0]")
        r = self.rpc_call("transfer", params)
        if r:
            print(f"SUCCESS — TX: {r['tx_hash']}, Fee: {r['fee']}")
        else:
            print("FAILED")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://127.0.0.1:28088")
    args = p.parse_args()
    Test(args.wallet_url).run()
