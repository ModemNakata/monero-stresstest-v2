#!/usr/bin/env python3
"""
Create 500 accounts, each with 500 subaddresses.
250,000 total addresses in the wallet.
"""

import requests
import json
import sys
import argparse
import time
from datetime import datetime, timezone

BATCH_SIZE = 50

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class WalletSetup:
    def __init__(self, wallet_url):
        self.url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc(self, method, params=None):
        if params is None:
            params = {}
        payload = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
        try:
            resp = self.session.post(self.url, json=payload, timeout=120)
            result = resp.json()
            if "error" in result and result["error"] is not None:
                err = result["error"]
                raise Exception(f"RPC Error {err.get('code', '?')}: {err.get('message', 'Unknown')}")
            return result.get("result", {})
        except Exception as e:
            raise

    def get_accounts(self):
        r = self.rpc("get_accounts", {})
        return r.get("subaddress_accounts", [])

    def get_addresses(self, account_index):
        r = self.rpc("get_address", {"account_index": account_index})
        return r.get("addresses", [])

    def create_account(self, label=""):
        params = {"label": label} if label else {}
        r = self.rpc("create_account", params)
        return r.get("account_index"), r.get("address")

    def create_addresses(self, account_index, count, label=""):
        params = {"account_index": account_index, "count": count}
        if label:
            params["label"] = label
        r = self.rpc("create_address", params)
        return r.get("addresses", [])

    def run(self, target_accounts=500, target_subaddresses=500):
        print(f"[{ts()}] === Wallet Structure Setup ===")
        print(f"[{ts()}] Target: {target_accounts} accounts x {target_subaddresses} subaddresses = {target_accounts * target_subaddresses} addresses")

        # Step 1: Check existing accounts
        print(f"\n[{ts()}] Checking existing accounts...")
        accounts = self.get_accounts()
        existing_accounts = len(accounts)
        print(f"[{ts()}] Existing accounts: {existing_accounts}")

        # Step 2: Create missing accounts
        if existing_accounts < target_accounts:
            to_create = target_accounts - existing_accounts
            print(f"[{ts()}] Creating {to_create} accounts...")
            for i in range(to_create):
                idx, addr = self.create_account(f"acc-{existing_accounts + i}")
                if i % 50 == 0 or i == to_create - 1:
                    print(f"[{ts()}]   Created account {existing_accounts + i + 1}/{target_accounts} (idx={idx})")
            accounts = self.get_accounts()
            existing_accounts = len(accounts)
            print(f"[{ts()}] Total accounts now: {existing_accounts}")
        else:
            print(f"[{ts()}] Already have {existing_accounts} accounts, skipping creation")

        # Step 3: For each account, ensure target_subaddresses subaddresses
        print(f"\n[{ts()}] Checking subaddresses per account...")

        total_existing_subs = 0
        total_to_create = 0

        for acc in accounts:
            idx = acc.get("account_index")
            addrs = self.get_addresses(idx)
            num_subs = len(addrs)
            total_existing_subs += num_subs
            if num_subs < target_subaddresses:
                total_to_create += target_subaddresses - num_subs

        print(f"[{ts()}] Existing subaddresses: {total_existing_subs}")
        print(f"[{ts()}] Subaddresses to create: {total_to_create}")

        # Step 4: Create subaddresses in batches
        if total_to_create > 0:
            print(f"\n[{ts()}] Creating subaddresses (batch size: {BATCH_SIZE})...")
            created = 0
            for acc in accounts:
                idx = acc.get("account_index")
                addrs = self.get_addresses(idx)
                num_subs = len(addrs)
                if num_subs >= target_subaddresses:
                    continue
                needed = target_subaddresses - num_subs
                for batch_start in range(0, needed, BATCH_SIZE):
                    batch_count = min(BATCH_SIZE, needed - batch_start)
                    try:
                        new_addrs = self.create_addresses(idx, batch_count, f"sub-{idx}")
                        created += len(new_addrs)
                    except Exception as e:
                        print(f"[{ts()}]   Error creating subaddresses for account {idx}: {e}")
                        time.sleep(1)
                        # Retry with smaller batch
                        for j in range(batch_count):
                            try:
                                self.create_addresses(idx, 1, f"sub-{idx}-{num_subs + batch_start + j}")
                                created += 1
                            except Exception as e2:
                                print(f"[{ts()}]   Failed subaddress {num_subs + batch_start + j}: {e2}")
                    if created % 1000 == 0:
                        print(f"[{ts()}]   Created {created}/{total_to_create} subaddresses")
            print(f"[{ts()}] Total subaddresses created: {created}")

        # Step 5: Final summary
        print(f"\n[{ts()}] === Final Summary ===")
        accounts = self.get_accounts()
        total_subs = 0
        for acc in accounts:
            idx = acc.get("account_index")
            addrs = self.get_addresses(idx)
            num_subs = len(addrs)
            total_subs += num_subs
            if idx < 5 or idx % 100 == 0:
                print(f"  Account {idx}: {num_subs} subaddresses")
        print(f"  Total accounts: {len(accounts)}")
        print(f"  Total subaddresses: {total_subs}")
        print(f"  Grand total addresses: {len(accounts) * target_subaddresses}")
        print(f"[{ts()}] === Done ===")


def main():
    parser = argparse.ArgumentParser(description="Create 500 accounts x 500 subaddresses in Monero wallet")
    parser.add_argument("--wallet-url", default="http://127.0.0.1:28088", help="Wallet RPC URL")
    parser.add_argument("--accounts", type=int, default=500, help="Number of accounts")
    parser.add_argument("--subaddresses", type=int, default=500, help="Subaddresses per account")
    args = parser.parse_args()

    setup = WalletSetup(args.wallet_url)
    try:
        setup.run(target_accounts=args.accounts, target_subaddresses=args.subaddresses)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n[{ts()}] Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
