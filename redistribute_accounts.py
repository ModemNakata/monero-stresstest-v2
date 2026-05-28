#!/usr/bin/env python3
"""
Monero Account Redistribute
Iterates through all accounts with balance, splits into 16 outputs
to random accounts using transfer_split with retry on -16 error.
"""

import requests
import json
import sys
import argparse
import random

NUM_DESTINATIONS = 16
TARGET_ACCOUNTS = 500
INITIAL_FEE_RESERVE = 1000000000
FEE_STEP = 5000000000

class MoneroRedistribute:
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
                err = result["error"]
                raise Exception(f"RPC Error {err.get('code', '?')}: {err.get('message', 'Unknown')}")
            return result.get("result", {})
        except Exception as e:
            return str(e), None

    def rpc_call_raw(self, method, params=None):
        """Returns (error_message_or_None, result_dict)"""
        if params is None:
            params = {}
        payload = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
        try:
            resp = self.session.post(self.wallet_url, json=payload, timeout=60)
            result = resp.json()
            if "error" in result and result["error"] is not None:
                err = result["error"]
                return f"RPC Error {err.get('code', '?')}: {err.get('message', 'Unknown')}", None
            return None, result.get("result", {})
        except Exception as e:
            return str(e), None

    def get_accounts(self):
        _, result = self.rpc_call_raw("get_accounts", {})
        if result is None:
            return []
        return result.get("subaddress_accounts", [])

    def get_balance(self, account_index):
        _, result = self.rpc_call_raw("get_balance", {"account_index": account_index})
        if result is None:
            return 0, 0, 0, []
        return (result.get("balance", 0), result.get("unlocked_balance", 0),
                result.get("blocks_to_unlock", 0), result.get("per_subaddress", []))

    def get_address(self, account_index):
        _, result = self.rpc_call_raw("get_address", {"account_index": account_index})
        if result is None:
            return None
        return result.get("address", None)

    def create_account(self, label=""):
        params = {"label": label} if label else {}
        _, result = self.rpc_call_raw("create_account", params)
        if result is None:
            return None
        return result.get("account_index", None)

    def transfer_split(self, from_account, destinations, amount_per_dest, subaddr_indices=None):
        dest_list = [{"amount": amount_per_dest, "address": a} for a in destinations]
        params = {"destinations": dest_list, "account_index": from_account, "priority": 0}
        if subaddr_indices is not None:
            params["subaddr_indices"] = subaddr_indices
        err, result = self.rpc_call_raw("transfer_split", params)
        return err, result

    def format_xmr(self, a):
        return a / 1e12

    def run(self):
        print()
        print("=" * 80)
        print("MONERO ACCOUNT REDISTRIBUTE")
        print("=" * 80)

        print("\nFetching accounts...")
        accounts = self.get_accounts()
        if not accounts:
            print("No accounts found!")
            return False

        num_accounts = len(accounts)
        print(f"  Existing accounts: {num_accounts}")

        if num_accounts < TARGET_ACCOUNTS:
            to_create = TARGET_ACCOUNTS - num_accounts
            print(f"\nCreating {to_create} more accounts to reach {TARGET_ACCOUNTS}...")
            for i in range(to_create):
                idx = self.create_account(f"pool-account-{num_accounts + i}")
                if idx is not None and (i + 1) % 50 == 0:
                    print(f"  Created {i + 1}/{to_create}")
            accounts = self.get_accounts()
            print(f"  Total accounts now: {len(accounts)}")

        account_addresses = {}
        for acc in accounts:
            idx, addr = acc.get("account_index"), acc.get("base_address")
            if idx is not None and addr:
                account_addresses[idx] = addr

        print(f"\nChecking balances and redistributing...")
        total_processed = total_skipped = total_failed = 0
        total_sent = total_fees = 0

        for acc in accounts:
            account_index = acc.get("account_index")
            label = acc.get("label", "")
            balance, unlocked, blocks_to_unlock, per_sub = self.get_balance(account_index)

            if unlocked == 0:
                total_skipped += 1
                continue

            subaddr_indices = [s["address_index"] for s in per_sub if s.get("unlocked_balance", 0) > 0]
            if not subaddr_indices:
                total_skipped += 1
                continue

            candidates = [i for i in account_addresses if i != account_index]
            if len(candidates) < NUM_DESTINATIONS:
                candidates = list(account_addresses.keys())
            chosen = random.sample(candidates, NUM_DESTINATIONS)
            dest_addrs = [account_addresses[i] for i in chosen]

            # Retry loop: increase fee reserve on -16 error
            fee_reserve = INITIAL_FEE_RESERVE
            success = False
            result = None
            last_error = None

            while True:
                if unlocked <= fee_reserve:
                    break

                per_dest = (unlocked - fee_reserve) // NUM_DESTINATIONS
                if per_dest == 0:
                    break

                print(f"\n  Account {account_index} ({label}):")
                print(f"    Balance: {self.format_xmr(balance):.12f}, Unlocked: {self.format_xmr(unlocked):.12f}, "
                      f"Blocks: {blocks_to_unlock}")
                print(f"    Reserve: {self.format_xmr(fee_reserve):.12f}, "
                      f"Splitting: {NUM_DESTINATIONS} x {self.format_xmr(per_dest):.12f}")
                print(f"    Destinations: {[f'Acc {c}' for c in chosen]}")

                err, result = self.transfer_split(account_index, dest_addrs, per_dest, subaddr_indices)
                if err is None:
                    success = True
                    break

                last_error = err
                print(f"    Failed: {err}")
                print(f"    Increasing reserve by {self.format_xmr(FEE_STEP):.12f}...")
                fee_reserve += FEE_STEP

            if not success:
                print(f"    Gave up after exhausting reserves. Last error: {last_error}")
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

            print(f"    Success after reserve={self.format_xmr(fee_reserve):.12f}: "
                  f"{len(tx_hashes)} tx(s), Amount: {self.format_xmr(tx_amount):.12f}, Fee: {self.format_xmr(tx_fee):.12f}")
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
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088")
    args = parser.parse_args()

    redist = MoneroRedistribute(args.wallet_url)
    success = redist.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
