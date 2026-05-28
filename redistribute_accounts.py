#!/usr/bin/env python3
"""
Monero Account Redistribute
Iterates through all accounts with balance, estimates fee via dry-run,
deducts fee from unlocked, splits remaining into 16 equal outputs,
and sends each to a random account (out of 500 total accounts).
"""

import requests
import json
import sys
import argparse
import random

NUM_DESTINATIONS = 16
TARGET_ACCOUNTS = 500

class MoneroRedistribute:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()

    def rpc_call(self, method, params=None):
        if params is None:
            params = {}
        payload = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": method,
            "params": params
        }
        try:
            response = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = response.json()
            if "error" in result and result["error"] is not None:
                error = result["error"]
                raise Exception(f"RPC Error {error.get('code', '?')}: {error.get('message', 'Unknown')}")
            return result.get("result", {})
        except Exception as e:
            print(f"    RPC error: {e}")
            return None

    def get_accounts(self):
        result = self.rpc_call("get_accounts", {})
        if result is None:
            return []
        return result.get("subaddress_accounts", [])

    def get_balance(self, account_index):
        result = self.rpc_call("get_balance", {"account_index": account_index})
        if result is None:
            return 0, 0, 0, []
        balance = result.get("balance", 0)
        unlocked = result.get("unlocked_balance", 0)
        blocks_to_unlock = result.get("blocks_to_unlock", 0)
        per_sub = result.get("per_subaddress", [])
        return balance, unlocked, blocks_to_unlock, per_sub

    def get_address(self, account_index):
        result = self.rpc_call("get_address", {"account_index": account_index})
        if result is None:
            return None
        return result.get("address", None)

    def create_account(self, label=""):
        params = {}
        if label:
            params["label"] = label
        result = self.rpc_call("create_account", params)
        if result is None:
            return None
        return result.get("account_index", None)

    def transfer_split(self, from_account, destinations, amount_per_dest, subaddr_indices=None):
        dest_list = []
        for addr in destinations:
            dest_list.append({
                "amount": amount_per_dest,
                "address": addr
            })
        params = {
            "destinations": dest_list,
            "account_index": from_account,
            "priority": 0
        }
        if subaddr_indices is not None:
            params["subaddr_indices"] = subaddr_indices
        result = self.rpc_call("transfer_split", params)
        return result

    def format_xmr(self, atomic_units):
        return atomic_units / 1e12

    def run(self):
        print()
        print("=" * 80)
        print("MONERO ACCOUNT REDISTRIBUTE")
        print("=" * 80)

        # Step 1: Get all accounts
        print("\nFetching accounts...")
        accounts = self.get_accounts()
        if not accounts:
            print("No accounts found!")
            return False

        num_accounts = len(accounts)
        print(f"  Existing accounts: {num_accounts}")

        # Step 2: Ensure 500 accounts exist
        if num_accounts < TARGET_ACCOUNTS:
            accounts_to_create = TARGET_ACCOUNTS - num_accounts
            print(f"\nCreating {accounts_to_create} more accounts to reach {TARGET_ACCOUNTS}...")
            for i in range(accounts_to_create):
                label = f"pool-account-{num_accounts + i}"
                idx = self.create_account(label)
                if idx is not None:
                    if (i + 1) % 50 == 0:
                        print(f"  Created {i + 1}/{accounts_to_create} accounts...")
            accounts = self.get_accounts()
            print(f"  Total accounts now: {len(accounts)}")

        # Build account_index -> primary address map
        account_addresses = {}
        for acc in accounts:
            idx = acc.get("account_index")
            addr = acc.get("base_address")
            if idx is not None and addr:
                account_addresses[idx] = addr

        # Step 3: Iterate through all accounts
        print(f"\nChecking balances and redistributing...")
        total_processed = 0
        total_skipped = 0
        total_failed = 0
        total_sent = 0
        total_fees = 0

        for acc in accounts:
            account_index = acc.get("account_index")
            label = acc.get("label", "")

            balance, unlocked, blocks_to_unlock, per_sub = self.get_balance(account_index)

            if unlocked == 0:
                total_skipped += 1
                continue

            # Only use subaddresses with unlocked balance > 0
            subaddr_indices = [s["address_index"] for s in per_sub if s.get("unlocked_balance", 0) > 0]
            if not subaddr_indices:
                total_skipped += 1
                continue

            # Pick 16 random destination accounts
            candidates = [idx for idx in account_addresses if idx != account_index]
            if len(candidates) < NUM_DESTINATIONS:
                candidates = list(account_addresses.keys())
            chosen = random.sample(candidates, NUM_DESTINATIONS)
            dest_addrs = [account_addresses[idx] for idx in chosen]

            # Reserve 0.005 XMR for fees (generous for 16-output tx), split the rest into 16
            FEE_RESERVE = 5000000000
            if unlocked <= FEE_RESERVE:
                total_skipped += 1
                continue

            per_dest = (unlocked - FEE_RESERVE) // NUM_DESTINATIONS
            print(f"\n  Account {account_index} ({label}):")
            print(f"    Balance: {self.format_xmr(balance):.12f} XMR, Unlocked: {self.format_xmr(unlocked):.12f} XMR, Blocks to unlock: {blocks_to_unlock}")
            print(f"    Spending from {len(subaddr_indices)} subaddress(es) with unlocked balance")
            print(f"    Splitting into {NUM_DESTINATIONS} x {self.format_xmr(per_dest):.12f} XMR")
            print(f"    Destinations: {[f'Acc {c}' for c in chosen]}")

            result = self.transfer_split(account_index, dest_addrs, per_dest, subaddr_indices)
            if result is None:
                total_failed += 1
                continue

            tx_hashes = result.get("tx_hash_list", [])
            fees = result.get("fee_list", [])
            amounts = result.get("amount_list", [])
            tx_fee = sum(fees)
            tx_amount = sum(amounts)

            total_processed += 1
            total_sent += tx_amount
            total_fees += tx_fee

            print(f"    Success: {len(tx_hashes)} tx(s), Amount: {self.format_xmr(tx_amount):.12f} XMR, Fee: {self.format_xmr(tx_fee):.12f} XMR")
            for h in tx_hashes:
                print(f"      TX: {h}")

        print(f"\n" + "=" * 80)
        print("REDISTRIBUTION COMPLETE")
        print("=" * 80)
        print(f"  Accounts processed: {total_processed}")
        print(f"  Accounts failed:    {total_failed}")
        print(f"  Accounts skipped:   {total_skipped}")
        print(f"  Total XMR sent:     {self.format_xmr(total_sent):.12f}")
        print(f"  Total fees paid:    {self.format_xmr(total_fees):.12f}")
        print("=" * 80 + "\n")

        return True

def main():
    parser = argparse.ArgumentParser(
        description="Redistribute balances across accounts by splitting into 16 outputs to random accounts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 redistribute_accounts.py
  python3 redistribute_accounts.py --wallet-url http://localhost:28088
        """
    )
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    args = parser.parse_args()

    redist = MoneroRedistribute(args.wallet_url)
    success = redist.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
