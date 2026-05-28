#!/usr/bin/env python3
"""Show all balances: account_index : subaddress_index : unlocked : locked"""

import requests, json, sys, argparse

def rpc_call(url, method, params=None):
    if params is None:
        params = {}
    try:
        r = requests.post(f"{url}/json_rpc", json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=30)
        result = r.json()
        if "error" in result and result["error"] is not None:
            return None
        return result.get("result", {})
    except:
        return None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://192.168.1.188:28088")
    args = p.parse_args()
    url = args.wallet_url

    accounts = rpc_call(url, "get_accounts", {})
    if not accounts:
        print("No accounts found")
        return
    accounts = accounts.get("subaddress_accounts", [])

    print("account_index : subaddress_index : unlocked : locked")
    for acc in accounts:
        aidx = acc["account_index"]
        r = rpc_call(url, "get_balance", {"account_index": aidx})
        if r is None:
            continue
        for sub in r.get("per_subaddress", []):
            unlocked = sub.get("unlocked_balance", 0)
            total = sub.get("balance", 0)
            locked = total - unlocked
            print(f"{aidx} : {sub['address_index']} : {unlocked} : {locked}")

    # Total
    r = rpc_call(url, "get_balance", {"all_accounts": True})
    if r:
        total = r.get("balance", 0)
        unlocked = r.get("unlocked_balance", 0)
        locked = total - unlocked
        print(f"total : : {unlocked} : {locked}")

if __name__ == "__main__":
    main()
