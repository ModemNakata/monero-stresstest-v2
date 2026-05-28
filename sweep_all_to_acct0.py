#!/usr/bin/env python3
"""Iterate all accounts/subaddresses, sweeping each to account 0 / address 0."""

import requests
import sys
import time
import argparse
from datetime import datetime, timezone

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class Sweeper:
    def __init__(self, wallet_url="http://192.168.1.188:28088"):
        self.url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc(self, method, params=None):
        if params is None:
            params = {}
        try:
            r = self.session.post(self.url, json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params}, timeout=120)
            result = r.json()
            if "error" in result and result["error"] is not None:
                return None, f"RPC Error {result['error']['code']}: {result['error']['message']}"
            return result.get("result", {}), None
        except Exception as e:
            return None, str(e)

    def get_dest_address(self):
        result, err = self.rpc("get_address", {"account_index": 0, "address_index": 0})
        if err:
            print(f"  Failed to get destination address: {err}")
            sys.exit(1)
        addr = result.get("address", "")
        if not addr:
            print("  No address for account 0 / address 0")
            sys.exit(1)
        return addr

    def run(self):
        dest = self.get_dest_address()
        print(f"[{ts()}] Destination: {dest} (account=0, subaddr=0)")

        accs, err = self.rpc("get_accounts", {})
        if err:
            print(f"  Failed to get accounts: {err}")
            sys.exit(1)

        accounts = accs.get("subaddress_accounts", [])
        print(f"[{ts()}] Found {len(accounts)} account(s)")

        total_sent = 0
        total_fee = 0
        tx_count = 0

        for acc in accounts:
            aidx = acc["account_index"]
            result, err = self.rpc("get_address", {"account_index": aidx})
            if err:
                print(f"  [A{aidx}] Failed to get addresses: {err}")
                continue

            addresses = result.get("addresses", [])
            print(f"  [A{aidx}] {len(addresses)} subaddress(es)")

            for addr_info in addresses:
                sidx = addr_info["address_index"]
                if aidx == 0 and sidx == 0:
                    print(f"    [A{aidx},S{sidx}] Skipping (destination)")
                    continue

                addr = addr_info["address"]
                print(f"    [A{aidx},S{sidx}] Sweeping {addr} ...", end=" ", flush=True)

                params = {
                    "address": dest,
                    "account_index": aidx,
                    "subaddr_indices": [sidx],
                    "priority": 0,
                    "get_tx_keys": True,
                }
                result, err = self.rpc("sweep_all", params)
                if err:
                    print(f"FAILED: {err}")
                    continue

                hashes = result.get("tx_hash_list", [])
                amounts = result.get("amount_list", [])
                fees = result.get("fee_list", [])
                n = len(hashes)
                sent_sum = sum(amounts) / 1e12
                fee_sum = sum(fees) / 1e12
                print(f"OK ({n} tx(s), {sent_sum:.12f} sent, {fee_sum:.12f} fee)")
                for i, h in enumerate(hashes):
                    amt = amounts[i] / 1e12 if i < len(amounts) else 0
                    fee = fees[i] / 1e12 if i < len(fees) else 0
                    print(f"      TX {i+1}: {h}  amt={amt:.12f}  fee={fee:.12f}")
                total_sent += sent_sum
                total_fee += fee_sum
                tx_count += n

                time.sleep(0.5)

        print(f"\n[{ts()}] Done — {tx_count} tx(s), "
              f"{total_sent:.12f} XMR sent, {total_fee:.12f} XMR in fees")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wallet-url", default="http://192.168.1.188:28088")
    args = p.parse_args()
    try:
        Sweeper(args.wallet_url).run()
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(0)
